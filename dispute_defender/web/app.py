"""Approval page (T-006, ADR-004, ADR-010).

Flow: list disputes -> dispute page (merchant enters tracking and carrier) -> draft page
(claims with verdicts and reasons, rendered text, payload preview, gate result) ->
approve -> result page with the state read back from PayPal.

Safety rules, all enforced on the server:
- Approve trusts nothing from the browser except tracking, carrier, the CSRF token and
  the hash of the text that was shown. It reads the dispute again, refuses before any
  model call if PayPal does not offer provide-evidence, drafts, verifies and renders
  again, and sends only if prepare_send() returns a plan (VERIFIED claims only, hash match).
- In dry mode (the default) everything runs except the provide-evidence POST.
- The state shown after approving is read back from PayPal, never assumed.
- No persistence: the process keeps only the CSRF key and used nonces.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from starlette.middleware.trustedhost import TrustedHostMiddleware

from dispute_defender.claims import MerchantOrderRecord, verify_claims
from dispute_defender.drafter import DrafterError, ModelClient, draft_claims
from dispute_defender.paypal import Dispute, PayPalClient, PayPalError, check_dispute_id
from dispute_defender.response import (
    ALLOWED_CARRIERS,
    Refusal,
    SendPlan,
    check_dispute_sendable,
    notes_hash,
    prepare_send,
    render_notes,
)

from .csrf import CsrfTokens
from .forms import FormError, merchant_record
from .settings import ALLOWED_HOSTS, SendMode
from .views import claim_views, dispute_view, shown

TEMPLATES = Path(__file__).parent / "templates"
PURPOSE_DRAFT = "draft"
PURPOSE_APPROVE = "approve"

logger = logging.getLogger("dispute_defender.web")

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


class _PageError(Exception):
    def __init__(self, status: int, title: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.title = title
        self.message = message


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_app(
    *,
    paypal: PayPalClient,
    model_client: ModelClient,
    model_id: str,
    send_mode: SendMode = "dry",
    csrf: CsrfTokens | None = None,
    now: Callable[[], datetime] = _utc_now,
) -> FastAPI:
    live = send_mode == "live"
    tokens = csrf or CsrfTokens()
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True, undefined=StrictUndefined)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(ALLOWED_HOSTS), www_redirect=False)

    @app.middleware("http")
    async def _security_headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    def page(name: str, status: int = 200, **context: Any) -> HTMLResponse:
        html = env.get_template(name).render(live=live, model_id=model_id, **context)
        return HTMLResponse(html, status_code=status)

    def message(status: int, title: str, text: str, back: str | None = None) -> HTMLResponse:
        return page("message.html", status=status, title=title, message=text, back=back)

    def read_time() -> str:
        return now().astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # --- errors: every message shown here is already safe (see the error classes) ---

    @app.exception_handler(_PageError)
    async def _page_error(_: Request, exc: _PageError) -> HTMLResponse:
        return message(exc.status, exc.title, exc.message)

    @app.exception_handler(FormError)
    async def _form_error(_: Request, exc: FormError) -> HTMLResponse:
        return message(422, "Invalid input", f"Nothing was sent. {exc}")

    @app.exception_handler(PayPalError)
    async def _paypal_error(_: Request, exc: PayPalError) -> HTMLResponse:
        return message(502, "PayPal error", f"Nothing more was done. {type(exc).__name__}: {exc}")

    @app.exception_handler(DrafterError)
    async def _drafter_error(_: Request, exc: DrafterError) -> HTMLResponse:
        return message(502, "Draft failed", f"Nothing was sent. {type(exc).__name__}: {exc}")

    @app.exception_handler(Exception)
    async def _internal_error(_: Request, exc: Exception) -> HTMLResponse:
        logger.error("internal error: %s", type(exc).__name__)  # class name only, never the message
        return message(500, "Internal error", "Internal error. Nothing was sent.")

    # --- helpers ---

    def valid_id(raw: str) -> str:
        try:
            return check_dispute_id(raw)
        except ValueError:
            raise _PageError(400, "Bad request", "Invalid dispute ID.") from None

    def check_csrf(request: Request, token: str, dispute_id: str, purpose: str) -> None:
        origin = request.headers.get("origin")
        if origin is not None and origin != f"{request.url.scheme}://{request.headers.get('host', '')}":
            raise _PageError(403, "Forbidden", "Cross-origin request refused. Nothing was sent.")
        if not tokens.consume(token, dispute_id, purpose):
            raise _PageError(
                403, "Forbidden",
                "The form token is missing, invalid, expired or already used. "
                "Nothing was sent. Reload the dispute page and try again.",
            )

    def draft_and_verify(dispute: Dispute, record: MerchantOrderRecord) -> list[Any]:
        drafted = draft_claims(dispute, record, client=model_client, model_id=model_id)
        return verify_claims(dispute, drafted.claims, record)

    def draft_page(dispute_id: str, dispute: Dispute, record: MerchantOrderRecord, results: list[Any],
                   *, notice: str | None = None, status: int = 200) -> HTMLResponse:
        notes = render_notes(results)
        outcome = prepare_send(dispute, results, notes_hash(notes) if notes is not None else "")
        approve = None
        if isinstance(outcome, SendPlan):
            approve = {
                "csrf": tokens.issue(dispute_id, PURPOSE_APPROVE),
                "shown_hash": outcome.notes_hash,
                "payload": shown(json.dumps(outcome.evidence.to_payload(), indent=2, ensure_ascii=False), None),
            }
        return page(
            "draft.html", status=status,
            dispute=dispute_view(dispute), claims=claim_views(results),
            notes=shown(notes, None) if notes is not None else None,
            refusal=outcome.reason if isinstance(outcome, Refusal) else None,
            approve=approve, notice=notice,
            tracking=record.tracking_number, carrier=record.carrier,
            read_at=read_time(),
        )

    def refused_page(dispute: Dispute, refusal: Refusal) -> HTMLResponse:
        return message(
            409, "Cannot respond now",
            f"Nothing was sent and no draft was made. {refusal.reason}.",
            back=f"/disputes/{dispute.dispute_id}",
        )

    # --- routes ---

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        items = paypal.list_disputes()
        rows = [
            {
                "dispute_id": shown(item.dispute_id), "status": shown(item.status), "stage": shown(item.stage),
                "reason": shown(item.reason),
                "amount": shown(f"{item.amount.value} {item.amount.currency_code}" if item.amount else None),
            }
            for item in items
        ]
        return page("list.html", disputes=rows, read_at=read_time())

    @app.get("/disputes/{dispute_id}", response_class=HTMLResponse)
    def show_dispute(dispute_id: str) -> HTMLResponse:
        did = valid_id(dispute_id)
        dispute = paypal.get_dispute(did)
        refusal = check_dispute_sendable(dispute)
        return page(
            "dispute.html", dispute=dispute_view(dispute),
            refusal=refusal.reason if refusal else None,
            csrf=tokens.issue(did, PURPOSE_DRAFT), carriers=ALLOWED_CARRIERS, read_at=read_time(),
        )

    @app.post("/disputes/{dispute_id}/draft", response_class=HTMLResponse)
    def draft(
        request: Request, dispute_id: str,
        tracking: str = Form(""), carrier: str = Form(""), csrf: str = Form(""),
    ) -> HTMLResponse:
        did = valid_id(dispute_id)
        check_csrf(request, csrf, did, PURPOSE_DRAFT)
        record = merchant_record(tracking, carrier)
        dispute = paypal.get_dispute(did)
        refusal = check_dispute_sendable(dispute)
        if refusal is not None:
            return refused_page(dispute, refusal)
        return draft_page(did, dispute, record, draft_and_verify(dispute, record))

    @app.post("/disputes/{dispute_id}/approve", response_class=HTMLResponse)
    def approve(
        request: Request, dispute_id: str,
        tracking: str = Form(""), carrier: str = Form(""), csrf: str = Form(""), shown_hash: str = Form(""),
    ) -> HTMLResponse:
        did = valid_id(dispute_id)
        check_csrf(request, csrf, did, PURPOSE_APPROVE)
        record = merchant_record(tracking, carrier)
        before = paypal.get_dispute(did)
        refusal = check_dispute_sendable(before)
        if refusal is not None:
            return refused_page(before, refusal)  # before any model call
        results = draft_and_verify(before, record)
        outcome = prepare_send(before, results, shown_hash)
        if isinstance(outcome, Refusal):
            return draft_page(did, before, record, results, status=409,
                              notice=f"Nothing was sent: {outcome.reason}.")

        sent = False
        if live:
            paypal.provide_evidence(did, [outcome.evidence])
            sent = True

        after = None
        readback_error = None
        try:
            after = dispute_view(paypal.get_dispute(did))
        except PayPalError as exc:
            readback_error = f"{type(exc).__name__}: {exc}"
        return page(
            "result.html", sent=sent, notes=shown(outcome.notes, None),
            tracking=shown(outcome.evidence.tracking_info[0].tracking_number),
            carrier=shown(outcome.evidence.tracking_info[0].carrier_name),
            before=dispute_view(before), after=after, readback_error=readback_error,
            read_at=read_time(),
        )

    @app.get("/disputes/{dispute_id}/state", response_class=HTMLResponse)
    def state(dispute_id: str) -> HTMLResponse:
        did = valid_id(dispute_id)
        return page("state.html", dispute=dispute_view(paypal.get_dispute(did)), read_at=read_time())

    return app
