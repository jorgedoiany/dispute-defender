"""Part A runner: the real drafter on SIMULATED scenarios, with cost controls (T-007).

- Every call goes through `scored_row` (draft_claims, verify_claims, the send gate).
- Hard cap on calls (the file's earlier attempts count too), ceiling MAX_CALLS_CEILING.
- Abort on a config error, on throttling (after the client's own bounded retries) and
  after MAX_CONSECUTIVE_ERRORS errors in a row. No retries beyond BedrockModelClient's.
- Resume: a call whose (scenario, model ID, repetition) already has an accepted or
  rejected line in the output file is skipped. Error lines are retried within the cap.
- Each line is written and flushed right after its call.
Raw lines hold no prompt, no buyer message text and no credentials.
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from dispute_defender.drafter import ModelClient, build_prompt, tool_spec

from .scenarios import REPO_ROOT, Scenario
from .scoring import scored_row

DEFAULT_MAX_CALLS = 144
MAX_CALLS_CEILING = 200
MAX_CONSECUTIVE_ERRORS = 3
ABORT_AT_ONCE = ("ModelConfigError", "ModelThrottledError")
# Heuristic for the estimate only, not a tokenizer: scenario N1 (system + user text + tool
# spec, 4,756 characters) then estimates ~2,070 tokens, near the ~2,020 input tokens T-005
# observed for a prompt of the same shape.
CHARS_PER_TOKEN = 2.3
EST_OUTPUT_TOKENS = 400  # T-005 observed 266-267 output tokens per call; rounded up
SECONDS_PER_CALL = (3, 10)  # assumption; T-005 did not record call times
EVAL_FORMAT = 1


@dataclass(frozen=True)
class ModelChoice:
    label: str  # primary or secondary
    model_id: str


@dataclass(frozen=True)
class Prices:
    """Author-supplied USD prices per million tokens; never built in."""
    in_per_m: float
    out_per_m: float
    supplied_on: str


@dataclass
class Plan:
    scenarios: list[Scenario]
    models: list[ModelChoice]
    repetitions: int
    out_path: Path
    attempts_in_file: int = 0
    done: set[tuple[str, str, int]] = field(default_factory=set)
    todo: list[tuple[int, ModelChoice, Scenario]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.scenarios) * len(self.models) * self.repetitions


def read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_plan(scenarios: Sequence[Scenario], models: Sequence[ModelChoice], repetitions: int,
               out_path: Path) -> Plan:
    rows = read_rows(out_path)
    done = {(r["scenario_id"], r["model_id"], r["repetition"]) for r in rows if r["outcome"] in ("accepted", "rejected")}
    plan = Plan(list(scenarios), list(models), repetitions, out_path, attempts_in_file=len(rows), done=done)
    for rep in range(1, repetitions + 1):  # repetition outermost, so a partial run stays balanced
        for model in models:
            for scenario in scenarios:
                if (scenario.id, model.model_id, rep) not in done:
                    plan.todo.append((rep, model, scenario))
    return plan


def estimated_input_tokens(scenario: Scenario) -> int:
    prompt = build_prompt(scenario.dispute, scenario.record)
    chars = len(prompt.system) + len(prompt.user_text) + len(json.dumps(tool_spec()))
    return math.ceil(chars / CHARS_PER_TOKEN)


def estimate(plan: Plan) -> dict[str, dict[str, int]]:
    per_model: dict[str, dict[str, int]] = {}
    for model in plan.models:
        todo = [s for _, m, s in plan.todo if m == model]
        per_model[model.model_id] = {
            "calls": len(todo),
            "input_tokens": sum(estimated_input_tokens(s) for s in todo),
            "output_tokens": EST_OUTPUT_TOKENS * len(todo),
        }
    return per_model


def cap_problem(plan: Plan, max_calls: int) -> str | None:
    needed = plan.attempts_in_file + len(plan.todo)
    if needed > max_calls:
        return (f"refused: the plan needs {len(plan.todo)} more call(s) and {_shown_path(plan.out_path)} already holds "
                f"{plan.attempts_in_file} attempt(s), {needed} in total, over the cap of {max_calls} (--max-calls)")
    return None


def _shown_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def format_plan(plan: Plan, max_calls: int, prices: Prices | None, freeze_line: str) -> str:
    est = estimate(plan)
    lines = [
        "T-007 evaluation plan (SIMULATED scenarios)",
        f"scenarios: {len(plan.scenarios)} | repetitions: {plan.repetitions} | models: {len(plan.models)}",
    ]
    for model in plan.models:
        e = est[model.model_id]
        lines.append(f"  {model.label:<9} {model.model_id:<46} {e['calls']:>4} calls | "
                     f"est. input ~{e['input_tokens']:,} tokens | est. output ~{e['output_tokens']:,} tokens")
    todo = len(plan.todo)
    lines += [
        f"calls: {plan.total} planned | already done in the output file: {plan.total - todo} | "
        f"to run now: {todo} | earlier attempts in the file: {plan.attempts_in_file} | cap: {max_calls}",
        f"token estimate: input = prompt characters / {CHARS_PER_TOKEN} (heuristic), output = {EST_OUTPUT_TOKENS} "
        "per call (T-005 observed 266-267); an estimate, not a measurement",
    ]
    if prices is None:
        lines.append("cost: not estimated (no prices given; pass --price-in-per-m and --price-out-per-m to print dollars)")
    else:
        e = est[plan.models[0].model_id]
        usd = e["input_tokens"] / 1e6 * prices.in_per_m + e["output_tokens"] / 1e6 * prices.out_per_m
        lines.append(f"cost: ~${usd:.2f} at author-supplied prices ${prices.in_per_m}/M input, "
                     f"${prices.out_per_m}/M output (supplied {prices.supplied_on})")
    lo, hi = (todo * s / 60 for s in SECONDS_PER_CALL)
    lines += [
        f"time: about {lo:.0f}-{hi:.0f} min sequential at {SECONDS_PER_CALL[0]}-{SECONDS_PER_CALL[1]} s per call (assumption)",
        f"freeze: {freeze_line}",
        f"output: {_shown_path(plan.out_path)}",
    ]
    return "\n".join(lines)


@dataclass(frozen=True)
class RunResult:
    calls_made: int
    aborted: str | None


def run_plan(plan: Plan, client: ModelClient, *, max_calls: int, hashes: dict[str, str],
             prices: Prices | None, now: Callable[[], datetime],
             log: Callable[[str], None] = print) -> RunResult:
    """Make the planned calls. The caller has already checked the cap, the freeze and --confirm-spend."""
    plan.out_path.parent.mkdir(parents=True, exist_ok=True)
    attempts = plan.attempts_in_file
    consecutive = 0
    made = 0
    with plan.out_path.open("a", encoding="utf-8") as out:
        for i, (rep, model, scenario) in enumerate(plan.todo, start=1):
            if attempts >= max_calls:
                return RunResult(made, f"cap of {max_calls} calls reached")
            run_at = now().isoformat(timespec="seconds")
            row = scored_row(scenario, client, model.model_id, rep)
            row.update(eval_format=EVAL_FORMAT, run_at=run_at, model_label=model.label, hashes=hashes,
                       author_prices=None if prices is None else vars(prices))
            out.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            out.flush()
            attempts += 1
            made += 1
            verdicts = "/".join(c["verdict"][0] for c in row["claims"])
            log(f"[{i}/{len(plan.todo)}] {scenario.id} {model.label} rep {rep}: {row['outcome']}"
                + (f" ({row['error_type']})" if row["error_type"] else "")
                + (f" | claims {len(row['claims'])} [{verdicts}] | sent={row['send']['sent']}" if row["send"] else ""))
            if row["outcome"] == "error":
                consecutive += 1
                if row["error_type"] in ABORT_AT_ONCE:
                    return RunResult(made, f"aborted on {row['error_type']}")
                if consecutive >= MAX_CONSECUTIVE_ERRORS:
                    return RunResult(made, f"aborted after {consecutive} errors in a row")
            else:
                consecutive = 0
    return RunResult(made, None)
