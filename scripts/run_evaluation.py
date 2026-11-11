#!/usr/bin/env python3
"""T-007 evaluation on SIMULATED scenarios (ADR-011). Not a measure of real-world accuracy.

Subcommands:
  faults   Part B: offline fault injection into the scenarios' correct claims. Free, no network.
  freeze   Record the hashes of scenarios, scoring, prompt and pipeline in evaluation/frozen.json.
  run      Part A: the real model drafts claims for each scenario. Billed Bedrock calls,
           only with --confirm-spend; --dry-run prints the plan and estimate and calls nothing.
  report   Write evaluation/results.md from the raw results, faults.json, the freeze and
           DECLARED_CHANGES.md. No network.

`run` reads `.env` without overriding variables already set in the shell (AWS_REGION,
BEDROCK_MODEL_ID, BEDROCK_MODEL_ID_SECONDARY) and, for a live run only, AWS credentials
through boto3's credential chain. It never calls PayPal.

Exit codes: 0 ok, 1 config or scenario error, 2 usage, 3 --confirm-spend missing,
4 run aborted, 5 refused (cap or freeze).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dispute_defender.drafter import (  # noqa: E402
    BedrockModelClient,
    DrafterError,
    ModelClient,
    ModelConfig,
    load_model_config,
)
from dispute_defender.evaluation.faults import run_faults  # noqa: E402
from dispute_defender.evaluation.freeze import (  # noqa: E402
    FROZEN_PATH,
    current_hashes,
    freeze,
    freeze_status,
    load_freezes,
)
from dispute_defender.evaluation.report import build_report  # noqa: E402
from dispute_defender.evaluation.runner import (  # noqa: E402
    DEFAULT_MAX_CALLS,
    MAX_CALLS_CEILING,
    ModelChoice,
    Prices,
    build_plan,
    cap_problem,
    format_plan,
    read_rows,
    run_plan,
)
from dispute_defender.evaluation.scenarios import EVAL_DIR, ScenarioError, load_scenarios  # noqa: E402

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
RESULTS_DIR = EVAL_DIR / "results"
FAULTS_PATH = RESULTS_DIR / "faults.json"
REPORT_PATH = EVAL_DIR / "results.md"
DECLARED_PATH = EVAL_DIR / "DECLARED_CHANGES.md"

ClientFactory = Callable[[ModelConfig], ModelClient]


def _now() -> datetime:
    return datetime.now(UTC)


def bedrock_client(config: ModelConfig) -> ModelClient:
    return BedrockModelClient.from_config(config)


def max_calls_arg(value: str) -> int:
    n = int(value)
    if not 1 <= n <= MAX_CALLS_CEILING:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_CALLS_CEILING}")
    return n


def positive_price(value: str) -> float:
    n = float(value)
    if not n > 0:
        raise argparse.ArgumentTypeError("must be a positive number")
    return n


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="T-007 evaluation on SIMULATED scenarios (not real-world accuracy).")
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("faults", help="Part B: offline fault injection (free)")
    f.add_argument("--out", type=Path, default=FAULTS_PATH)

    sub.add_parser("freeze", help="record the hashes of scenarios, scoring, prompt and pipeline")

    rep = sub.add_parser("report", help="write evaluation/results.md from the recorded results")
    rep.add_argument("--raw", type=Path, nargs="*", help="raw JSONL files (default: evaluation/results/raw-*.jsonl)")
    rep.add_argument("--faults", type=Path, default=FAULTS_PATH)
    rep.add_argument("--out", type=Path, default=REPORT_PATH)

    r = sub.add_parser("run", help="Part A: billed Bedrock calls, only with --confirm-spend")
    r.add_argument("--model", choices=("primary", "secondary", "both"), default="both")
    r.add_argument("--repetitions", type=int, choices=range(1, 6), default=3, metavar="1-5")
    r.add_argument("--scenarios", help="comma-separated scenario IDs (default: all)")
    r.add_argument("--max-calls", type=max_calls_arg, default=DEFAULT_MAX_CALLS,
                   help=f"hard cap on attempts in the output file, at most {MAX_CALLS_CEILING} (default {DEFAULT_MAX_CALLS})")
    r.add_argument("--out", type=Path, help="raw JSONL output; an existing file is resumed "
                   "(default: evaluation/results/raw-<UTC date>.jsonl)")
    r.add_argument("--price-in-per-m", type=positive_price, help="author-supplied USD per million input tokens")
    r.add_argument("--price-out-per-m", type=positive_price, help="author-supplied USD per million output tokens")
    mode = r.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the plan and estimate; call nothing")
    mode.add_argument("--confirm-spend", action="store_true", help="make the billed Bedrock calls")
    return p


def cmd_faults(args: argparse.Namespace) -> int:
    data = run_faults(load_scenarios())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Part B (SIMULATED, offline): {len(data['rows'])} fault cases on {data['scenario_count']} scenarios "
          f"-> {args.out.name}")
    print(f"baseline: {data['baseline']['wrongly_rejected']} of {data['baseline']['correct_claims']} "
          "correct claims wrongly rejected")
    keys = ("applied", "caught", "missed", "expected_miss", "verified", "wrongly_rejected",
            "rejected_by_design", "reached_send")
    print("group".ljust(18) + "".join(k.rjust(19) for k in keys))
    for group, counts in data["summary"].items():
        print(group.ljust(18) + "".join(str(counts.get(k, 0)).rjust(19) for k in keys))
    return 0


def cmd_freeze(_args: argparse.Namespace) -> int:
    entry = freeze(_now())
    print(f"frozen at {entry['frozen_at']} -> {FROZEN_PATH}")
    for name, digest in entry["hashes"].items():
        print(f"  {name:<9} {digest}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    raw_files = args.raw if args.raw is not None else sorted(RESULTS_DIR.glob("raw-*.jsonl"))
    rows = [row for path in raw_files for row in read_rows(path)]
    faults = json.loads(args.faults.read_text(encoding="utf-8")) if args.faults.exists() else None
    declared = DECLARED_PATH.read_text(encoding="utf-8") if DECLARED_PATH.exists() else None
    text = build_report(rows, faults, load_freezes(), declared, current_hashes(), _now())
    args.out.write_text(text, encoding="utf-8")
    print(f"report: {len(rows)} raw result line(s) from {len(raw_files)} file(s), "
          f"Part B {'included' if faults else 'missing'} -> {args.out.name}")
    return 0


def cmd_run(args: argparse.Namespace, client_factory: ClientFactory) -> int:
    if (args.price_in_per_m is None) != (args.price_out_per_m is None):
        print("refused: pass both --price-in-per-m and --price-out-per-m, or neither", file=sys.stderr)
        return 2
    if args.price_in_per_m is not None and args.model == "both":
        print("refused: prices are per model; run --model primary and --model secondary separately "
              "to price each", file=sys.stderr)
        return 2
    config = load_model_config()
    labels = ("primary", "secondary") if args.model == "both" else (args.model,)
    models = [ModelChoice(label, config.model(label)) for label in labels]
    scenarios = load_scenarios(ids=args.scenarios.split(",") if args.scenarios else None)
    today = _now().date().isoformat()
    out = args.out or RESULTS_DIR / f"raw-{today}.jsonl"
    prices = None if args.price_in_per_m is None else Prices(args.price_in_per_m, args.price_out_per_m, today)
    plan = build_plan(scenarios, models, args.repetitions, out)

    status, last = freeze_status()
    freeze_line = {
        "missing": "no freeze recorded; run `freeze` and commit evaluation/frozen.json before a live run",
        "match": f"current hashes match evaluation/frozen.json (frozen at {last['frozen_at'] if last else ''})",
        "differs": "current hashes DIFFER from the last freeze; a live run is refused until a new freeze "
                   "is recorded and the change is declared in evaluation/DECLARED_CHANGES.md",
    }[status]
    print(format_plan(plan, args.max_calls, prices, freeze_line))

    if args.dry_run:
        print("dry run: no Bedrock client created, no call made")
        return 0
    if not args.confirm_spend:
        print("not run: pass --confirm-spend to make these billed Bedrock calls (or --dry-run)", file=sys.stderr)
        return 3
    if status != "match":
        print(f"refused: freeze {status}", file=sys.stderr)
        return 5
    problem = cap_problem(plan, args.max_calls)
    if problem:
        print(problem, file=sys.stderr)
        return 5
    if not plan.todo:
        print("nothing to run: every planned call is already in the output file")
        return 0
    client = client_factory(config)
    result = run_plan(plan, client, max_calls=args.max_calls, hashes=current_hashes(), prices=prices, now=_now)
    print(f"calls made: {result.calls_made}")
    if result.aborted:
        print(f"ABORTED: {result.aborted}; rerun the same command to resume", file=sys.stderr)
        return 4
    return 0


def main(argv: Sequence[str] | None = None, *, client_factory: ClientFactory = bedrock_client,
         env_file: Path | None = ENV_PATH) -> int:
    args = parser().parse_args(argv)
    if env_file is not None:
        load_dotenv(env_file, override=False)
    try:
        if args.command == "faults":
            return cmd_faults(args)
        if args.command == "freeze":
            return cmd_freeze(args)
        if args.command == "report":
            return cmd_report(args)
        return cmd_run(args, client_factory)
    except (DrafterError, ScenarioError) as exc:
        print(f"[evaluation] FAILED | {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
