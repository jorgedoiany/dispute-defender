"""Generate `evaluation/results.md` from the raw results (T-007, ADR-011).

Every number comes from `scoring.summarize` (Part A) or `faults.json` (Part B). The
report is labelled SIMULATED, states the freeze, includes declared changes and ends
with the limitations.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from .scoring import summarize

TITLE = "# T-007 evaluation results: SIMULATED DATA"
BANNER = (
    "> **Simulated scenarios only.** These numbers describe 24 simulated disputes written for this "
    "evaluation, with hand-written ground truth. They do **not** describe real-world accuracy, real "
    "PayPal disputes or real buyers."
)
LIMITATIONS = [
    "All scenarios are simulated and were written by the author with knowledge of the verifier's rules. "
    "One dispute reason (item not received); no real buyers or merchants.",
    "Small sample: 24 scenarios with up to 3 repetitions per model. Zero observed errors does not mean a zero "
    "error rate; no confidence intervals are claimed.",
    "The ground truth is hand-written and may itself be wrong; every claim where it and the verifier disagree "
    "is listed for review.",
    "The model only ever sees the UTC transaction date (computed by code). The date scenarios test whether a "
    "local date in a buyer message lures the model, not time-zone reasoning.",
    "The no-verifier counterfactual is computed from the same model outputs, not from a separate experiment. "
    "It keeps schema validation, so it is conservative and understates the verifier's value.",
    "The verifier trusts the merchant record: a wrong record is not caught (Part B expected misses).",
    "Part B faults were designed against known verifier rules, so a high catch rate is expected by construction.",
    "Two models, one region, one run window, no temperature sent (the model default). Other model versions or "
    "days may behave differently.",
    "The prompt-injection texts were written by the author; they are not adversarially optimised.",
    "Token estimates in the dry run are a heuristic. Any cost shown uses author-supplied prices.",
    "Nothing here says whether a response would win a dispute, or what PayPal would accept.",
]


def esc(value: Any) -> str:
    text = value if isinstance(value, str) else str(value)
    for a, b in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ("|", "\\|"), ("`", "\\`"), ("*", "\\*"),
                 ("_", "\\_"), ("[", "\\["), ("\r", " "), ("\n", " ")):
        text = text.replace(a, b)
    return text


def table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return out


def ratio(k: int, n: int) -> str:
    return f"{k}/{n}" + (f" ({100 * k / n:.1f}%)" if n else "")


def _declared(text: str | None) -> list[str]:
    if not text:
        return []
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith(("#", ">"))]
    return [] if lines == ["None declared."] else lines


def _freeze_section(rows: list[dict[str, Any]], freezes: list[dict[str, Any]], declared: list[str],
                    current: dict[str, str]) -> list[str]:
    out = ["## Freeze", ""]
    if not freezes:
        out.append("No freeze recorded in `evaluation/frozen.json`.")
        return out
    first = freezes[0]
    out.append(f"Scenarios, scoring rules, prompt and pipeline hashes were recorded at {first['frozen_at']} "
               f"(`evaluation/frozen.json`, {len(freezes)} freeze(s)).")
    run_sets = {tuple(sorted(r["hashes"].items())) for r in rows if r.get("hashes")}
    if rows:
        first_call = min(r["run_at"] for r in rows)
        before = datetime.fromisoformat(first["frozen_at"]) <= datetime.fromisoformat(first_call)
        same = run_sets == {tuple(sorted(first["hashes"].items()))}
        if before and same and len(freezes) == 1:
            out.append(f"They were frozen before the first live call ({first_call}), and all {len(rows)} recorded "
                       "calls ran with the frozen hashes. No change was made after seeing results.")
        else:
            if not before:
                out.append(f"**The first freeze is not earlier than the first live call ({first_call}).**")
            if len(run_sets) > 1:
                out.append(f"**The raw results carry {len(run_sets)} different hash sets: something changed after "
                           "a first run.**")
            elif not same:
                out.append("**The raw results ran with hashes that differ from the first freeze.**")
            if len(freezes) > 1:
                out.append(f"**{len(freezes) - 1} later freeze(s) recorded: a change after the first freeze.**")
            if not declared:
                out.append("**Undeclared change: `evaluation/DECLARED_CHANGES.md` declares nothing.**")
        if run_sets and run_sets != {tuple(sorted(current.items()))}:
            out.append("The current code or scenarios differ from the hashes the results ran with; this report "
                       "was generated from the recorded results.")
    else:
        status = "match" if first["hashes"] == current and len(freezes) == 1 else "do not match"
        out.append(f"No live call recorded yet. The current hashes {status} the first freeze.")
    out += [""] + table(["hash", "first freeze", "current"],
                        [(k, f"`{first['hashes'].get(k, '')[:16]}`", f"`{current.get(k, '')[:16]}`")
                         for k in sorted(current)])
    return out


def _part_a(rows: list[dict[str, Any]]) -> list[str]:
    out = ["## Part A: model drafts on simulated scenarios (live Bedrock)", ""]
    if not rows:
        out.append("Not run yet. Run `scripts/run_evaluation.py run --confirm-spend` (see AGENTS.md), then "
                   "`scripts/run_evaluation.py report`.")
        return out
    summary = summarize(rows)["models"]
    models = list(summary)
    run_ats = sorted(r["run_at"] for r in rows)
    out += [
        f"- Run window (UTC): {run_ats[0]} to {run_ats[-1]}",
        f"- Models: {', '.join(f'`{m}`' for m in models)}",
        f"- Scenarios: {len({r['scenario_id'] for r in rows})}; repetitions: up to {max(r['repetition'] for r in rows)}",
        f"- Calls recorded: {len(rows)}",
        "",
        "### Calls per model",
        "",
    ]
    cost_rows = []
    for m in models:
        prices = [r["author_prices"] for r in rows if r["model_id"] == m and r.get("author_prices")]
        if prices:
            p = prices[-1]
            s = summary[m]
            usd = s["input_tokens"] / 1e6 * p["in_per_m"] + s["output_tokens"] / 1e6 * p["out_per_m"]
            cost_rows.append((f"`{m}`", f"${p['in_per_m']}/M in, ${p['out_per_m']}/M out (supplied {p['supplied_on']})",
                              f"${usd:.2f}"))
    out += table(["model", "calls", "accepted", "rejected (M5)", "errors", "input tokens", "output tokens"],
                 [(f"`{m}`", s["calls"], s["accepted"], s["rejected"], s["errors"], s["input_tokens"],
                   s["output_tokens"]) for m, s in summary.items()])
    out += ["", "Errors (network, throttling, refused calls) are left out of every rate below."]
    if cost_rows:
        out += ["", "Cost from actual token counts at author-supplied prices (not checked by the code):", ""]
        out += table(["model", "author-supplied prices", "cost"], cost_rows)

    out += ["", "### Wrong claims at the send step: no verifier vs. with verifier (M2, M3)", "",
            "Incorrect claims are wrong values, claims about missing facts and unsupported claims (ADR-011).", ""]
    out += table(["model", "incorrect claims in accepted drafts = sent with no verifier (M2)",
                  "incorrect claims VERIFIED (M3)", "incorrect claims VERIFIED and in a send plan (M3)"],
                 [(f"`{m}`", s["incorrect_counterfactual_sent"], s["incorrect_verified"],
                   s["incorrect_reached_send"]) for m, s in summary.items()])
    out += ["", "M2 is a counterfactual computed from the **same model outputs**, counted as if every claim of "
            "every accepted draft were sent unchecked; it is not a separate experiment. It keeps schema "
            "validation (drafts rejected by the schema are not counted as sent), so it is conservative and "
            "understates the verifier's value. M3 is reported as observed."]

    out += ["", "### Model claim errors (M1)", ""]
    out += table(["model", "claims", "wrong value", "claim about a missing fact", "duplicates", "unsupported (not an error)",
                  "model errors", "drafts with a model error"],
                 [(f"`{m}`", s["claims"], s["classes"].get("wrong_value", 0), s["classes"].get("absent_fact", 0),
                   s["duplicates"], s["classes"].get("unsupported", 0), ratio(s["model_errors"], s["claims"]),
                   ratio(s["drafts_with_model_error"], s["accepted"])) for m, s in summary.items()])
    out += ["", "Per category:", ""]
    cat_rows = []
    for m, s in summary.items():
        for cat, c in s["per_category"].items():
            cat_rows.append((f"`{m}`", cat, c["calls"], c["accepted"], ratio(c["model_errors"], c["claims"]),
                             c["incorrect"], c["incorrect_verified"]))
    out += table(["model", "category", "calls", "accepted", "model errors / claims", "incorrect", "incorrect VERIFIED"],
                 cat_rows)

    out += ["", "### Correct claims wrongly rejected (M4)", ""]
    out += table(["model", "correct claims", "FLAGGED", "BLOCKED"],
                 [(f"`{m}`", s["classes"].get("correct", 0), s["correct_flagged"], s["correct_blocked"])
                  for m, s in summary.items()])

    out += ["", "### Drafts rejected before the verifier (M5)", ""]
    reasons = [(f"`{m}`", esc(reason), n) for m, s in summary.items() for reason, n in s["rejected_reasons"].items()]
    out += table(["model", "reason", "count"], reasons) if reasons else ["None."]

    out += ["", "### Variation across repetitions (M6)", ""]
    out += table(["model", "scenarios with identical output in every repetition", "scenarios that varied",
                  "scenarios with fewer than 2 completed repetitions"],
                 [(f"`{m}`", s["variation"]["identical"], len(s["variation"]["varying"]),
                   s["variation"]["too_few_repetitions"]) for m, s in summary.items()])
    varying = [(f"`{m}`", v["scenario_id"], ", ".join(v["types"]) or "-", ", ".join(v["outcomes"]))
               for m, s in summary.items() for v in s["variation"]["varying"]]
    if varying:
        out += [""] + table(["model", "scenario", "claim types that varied", "outcomes"], varying)

    out += ["", "### Ground truth by verdict (M7)", ""]
    xt_rows = []
    for m, s in summary.items():
        for cls in ("correct", "wrong_value", "absent_fact", "unsupported"):
            counts = s["crosstab"].get(cls, {})
            xt_rows.append((f"`{m}`", cls, counts.get("VERIFIED", 0), counts.get("FLAGGED", 0), counts.get("BLOCKED", 0)))
    out += table(["model", "ground truth", "VERIFIED", "FLAGGED", "BLOCKED"], xt_rows)
    out += ["", "Disagreements between ground truth and verifier (incorrect but VERIFIED, or correct but not VERIFIED):", ""]
    dis = [(f"`{m}`", d["scenario_id"], d["repetition"], d["type"], esc(d["value"]), d["truth"], d["verdict"],
            esc(d["reason"])) for m, s in summary.items() for d in s["disagreements"]]
    out += table(["model", "scenario", "rep", "type", "value", "ground truth", "verdict", "reason"], dis) if dis else ["None."]

    out += ["", "### Send outcome and coverage", ""]
    out += table(["model", "accepted drafts", "send plans", "send outcome differs from the scenario's expected_send",
                  "expected claims missing"],
                 [(f"`{m}`", s["accepted"], s["sent"], len(s["send_mismatches"]),
                   ratio(s["missing_expected"], s["expected_claims"])) for m, s in summary.items()])
    mism = [(f"`{m}`", x["scenario_id"], x["repetition"], x["expected"], "send" if x["sent"] else "refuse",
             esc(x["reason"] or "")) for m, s in summary.items() for x in s["send_mismatches"]]
    if mism:
        out += [""] + table(["model", "scenario", "rep", "expected", "actual", "refusal reason"], mism)
    return out


def _part_b(faults: dict[str, Any] | None) -> list[str]:
    out = ["## Part B: fault injection into simulated claims (offline)", ""]
    if not faults:
        out.append("Not run yet. Run `scripts/run_evaluation.py faults`.")
        return out
    b = faults["baseline"]
    s = faults["summary"]
    out += [
        f"{len(faults['rows'])} fault cases on {faults['scenario_count']} simulated scenarios. Each case alters one "
        "claim of a scenario's correct claims and runs the real verifier and send gate (claim layer), or returns a "
        "faulty tool call to `draft_claims` (tool-input layer). Deterministic and free.",
        "",
        f"Baseline: {b['wrongly_rejected']} of {b['correct_claims']} correct claims wrongly rejected.",
        "",
        "### Faults the verifier should catch",
        "",
    ]
    groups = [g for g in s if g not in ("benign_variant", "local_date")]
    out += table(["fault group", "applied", "caught", "missed", "expected misses", "faulted value reached a send plan"],
                 [(g, s[g]["applied"], s[g].get("caught", 0), s[g].get("missed", 0), s[g].get("expected_miss", 0),
                   s[g].get("reached_send", 0)) for g in groups])
    out += ["", "Expected misses are outside the verifier's reach by design: the merchant record itself is wrong and the "
            "claim copies it, so the claim matches the record. When the scenario sends, that wrong value reaches the "
            "send plan."]
    out += ["", "### Correct values that must not be rejected", ""]
    out += table(["group", "applied", "VERIFIED", "rejected"],
                 [(g, s[g]["applied"], s[g].get("verified", 0), s[g].get("wrongly_rejected", 0) + s[g].get("rejected_by_design", 0))
                  for g in ("benign_variant", "local_date") if g in s])
    out += ["", "`benign_variant`: equivalent values (an extra trailing zero, carrier case or spaces). `local_date`: the "
            "correct local date near midnight, BLOCKED by design because dates are compared in UTC (ADR-008); a known "
            "false rejection.", "",
            "The faults were written with knowledge of the verifier's rules, so a high catch rate is expected by "
            "construction."]
    misses = [r for r in faults["rows"] if r["outcome"] == "missed"]
    if misses:
        out += ["", "Unexpected misses:", ""]
        out += table(["scenario", "group", "fault", "verdict"],
                     [(r["scenario_id"], r["group"], esc(r["fault"]), r["verdict"]) for r in misses])
    return out


def build_report(rows: list[dict[str, Any]], faults: dict[str, Any] | None, freezes: list[dict[str, Any]],
                 declared_text: str | None, current: dict[str, str], generated_at: datetime) -> str:
    declared = _declared(declared_text)
    out = [TITLE, "", BANNER, "",
           f"Generated {generated_at.isoformat(timespec='seconds')} by `scripts/run_evaluation.py report`. "
           "Scoring definitions: ADR-011 in `DECISIONS.md`. Scenarios: `evaluation/scenarios/` (simulated).", ""]
    out += _freeze_section(rows, freezes, declared, current)
    out += ["", "## Declared changes", ""]
    out += [esc(line) for line in declared] if declared else ["None declared."]
    out += [""] + _part_a(rows) + [""] + _part_b(faults)
    out += ["", "## Limitations", ""] + [f"- {item}" for item in LIMITATIONS]
    return "\n".join(out) + "\n"
