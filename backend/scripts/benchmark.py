"""Benchmark five triage approaches on the held-out test set (all 250 rows, incl. the 50 hidden).

1. keyword rules      2. local classifier only      3. fast LLM only
4. reasoning LLM only (gpt-oss-120b on Groq, a reasoning model; gemini-3.5-flash fallback)
5. Sanket hybrid: local model -> fast LLM for uncertain reports -> safety rules

Reports are streamed at 25 per second (a surge) and every per-report latency is
measured from submission to final answer, so it includes queueing and rate
limits. Cost is the tokens each provider reported, at list price. Results go to
data/benchmark.json and docs/benchmark.md.

Run from ``backend/``: ``python -m scripts.benchmark``. Uses real API keys.
"""

import argparse
import asyncio
import json
import statistics
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.decision.factory import build_slots
from app.decision.llm import FallbackChain, LLMDecider, LLMOutcome, LLMStats, ProviderSlot
from app.decision.local import LocalClassifier
from app.decision.pipeline import DecisionPipeline
from app.decision.providers import GeminiProvider, OpenAICompatibleProvider, RateLimiter
from app.decision.rules import PrankTracker, SafetyRules
from app.models import DecisionResult, Price, Report
from scripts.baselines import KeywordTriage
from scripts.dataset import TEST_PATH, LabeledReport, load
from scripts.metrics import evaluate

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "data" / "benchmark.json"
MD_PATH = ROOT.parent / "docs" / "benchmark.md"
REPORTS_PER_SECOND = 25
REASONING_MODEL = "openai/gpt-oss-120b"
REASONING_FALLBACK = "gemini-3.5-flash"
QUOTA_RESET_PAUSE_S = 65  # let per-minute quotas refill before each LLM approach
QUOTA_WAIT_S = 60.0  # benchmark chains wait for quota instead of failing fast
MAX_RETRY_ROUNDS = 15  # LLM-only approaches re-ask unanswered reports after quotas refill
REASONING_BATCH = 10
REASONING_CAP_PER_ITEM = 300  # thinking tokens count against the output cap


@dataclass
class Run:
    name: str
    answers: list[DecisionResult | None]
    latencies_ms: list[float]
    stats: LLMStats | None = None
    notes: list[str] = field(default_factory=list)


def as_result(outcome: LLMOutcome | None, prompt_version: str) -> DecisionResult | None:
    if outcome is None:
        return None
    return DecisionResult(
        decision=outcome.decision,
        source="llm",
        confidence=outcome.decision.confidence,
        model=f"{outcome.provider}/{outcome.model}",
        prompt_version=prompt_version,
    )


async def stream(
    rows: Sequence[LabeledReport],
    chunk: int,
    decide: Callable[[list[Report]], Awaitable[list[DecisionResult | None]]],
    patient: bool = False,
) -> tuple[list[DecisionResult | None], list[float]]:
    """Submit chunks at REPORTS_PER_SECOND; latency = answer time - submit time, per report."""
    reports = [
        Report(id=r.id, channel="sms", caller_hash=f"bench-{r.id}", raw_text=r.text, received_at=time.time())
        for r in rows
    ]
    answers: list[DecisionResult | None] = [None] * len(rows)
    latencies = [0.0] * len(rows)
    submitted = [0.0] * len(rows)

    async def one(indices: list[int]) -> None:
        out = await decide([reports[i] for i in indices])
        now = time.perf_counter()
        for i, answer in zip(indices, out, strict=True):
            answers[i] = answer
            latencies[i] = (now - submitted[i]) * 1000

    tasks = []
    for start in range(0, len(rows), chunk):
        indices = list(range(start, min(start + chunk, len(rows))))
        for i in indices:
            submitted[i] = time.perf_counter()
        tasks.append(asyncio.create_task(one(indices)))
        await asyncio.sleep(chunk / REPORTS_PER_SECOND)
    await asyncio.gather(*tasks)
    # Free tiers run out mid-surge. A pure-LLM approach has no fallback, so to measure the
    # model rather than the quota, unanswered reports are re-asked once quotas refill;
    # their latency keeps counting from the original submission.
    for _round in range(MAX_RETRY_ROUNDS if patient else 0):
        missing = [i for i, a in enumerate(answers) if a is None]
        if not missing:
            break
        await asyncio.sleep(QUOTA_RESET_PAUSE_S)
        for start in range(0, len(missing), chunk):
            await one(missing[start : start + chunk])
    return answers, latencies


def rules() -> SafetyRules:
    return SafetyRules(PrankTracker(window_s=600, min_reports=3))


async def run_keyword(rows: Sequence[LabeledReport]) -> Run:
    triage = KeywordTriage()
    answers: list[DecisionResult | None] = []
    latencies: list[float] = []
    for row in rows:
        start = time.perf_counter()
        answers += triage.predict_batch([row.text])
        latencies.append((time.perf_counter() - start) * 1000)
    return Run("keyword rules", answers, latencies)


async def run_local(rows: Sequence[LabeledReport], classifier: LocalClassifier) -> Run:
    classifier.predict_batch([rows[0].text])  # warm-up

    async def decide(batch: list[Report]) -> list[DecisionResult | None]:
        return list(await asyncio.to_thread(classifier.predict_batch, [r.raw_text for r in batch]))

    answers, latencies = await stream(rows, 25, decide)
    return Run("local only", answers, latencies)


async def with_decider(decider: LLMDecider, work: Callable[[], Awaitable[Run]]) -> Run:
    runner = asyncio.create_task(decider.run())
    try:
        return await work()
    finally:
        runner.cancel()


async def run_llm(name: str, rows: Sequence[LabeledReport], decider: LLMDecider, chunk: int) -> Run:
    async def work() -> Run:
        async def decide(batch: list[Report]) -> list[DecisionResult | None]:
            outcomes = await decider.decide([r.raw_text for r in batch])
            return [as_result(o, decider.prompt_version) for o in outcomes]

        answers, latencies = await stream(rows, chunk, decide, patient=True)
        return Run(name, answers, latencies, decider.stats)

    return await with_decider(decider, work)


async def run_hybrid(rows: Sequence[LabeledReport], classifier: LocalClassifier, decider: LLMDecider, threshold: float) -> Run:
    pipeline = DecisionPipeline(classifier, decider, rules(), threshold)

    async def work() -> Run:
        async def decide(batch: list[Report]) -> list[DecisionResult | None]:
            return list(await pipeline.decide_batch(batch))

        answers, latencies = await stream(rows, 25, decide)
        local_share = sum(a is not None and a.source != "llm" for a in answers) / len(answers)
        return Run(
            "Sanket hybrid",
            answers,
            latencies,
            decider.stats,
            [
                f"{local_share:.0%} of reports decided without an LLM call (local model + rules)",
                "Latency here is to the *final* decision. Every report is on the board with its local "
                "decision within ~10 ms; uncertain ones are revised when the LLM answers.",
            ],
        )

    return await with_decider(decider, work)


def cost_inr(stats: LLMStats | None, prices: dict[str, Price], usd_to_inr: float) -> float:
    if stats is None:
        return 0.0
    total = 0.0
    for key in set(stats.input_tokens) | set(stats.output_tokens):
        model = key.split("/", 1)[-1]
        price = prices.get(model, Price(input=0.0, output=0.0))
        total += stats.input_tokens.get(key, 0) * price.input + stats.output_tokens.get(key, 0) * price.output
    return total / 1e6 * usd_to_inr


def summarise(run: Run, rows: Sequence[LabeledReport], settings: Settings) -> dict[str, Any]:
    metrics = evaluate(rows, run.answers)
    hidden = [i for i, r in enumerate(rows) if r.hidden]
    hidden_metrics = evaluate([rows[i] for i in hidden], [run.answers[i] for i in hidden])
    cost = cost_inr(run.stats, settings.llm_prices, settings.usd_to_inr)
    stats = run.stats
    return {
        "approach": run.name,
        "triage_acc": metrics["triage_acc"],
        "triage_acc_hidden50": hidden_metrics["triage_acc"],
        "emergency": metrics["emergency"],
        "department_acc": metrics["department_acc"],
        "severity_mae": metrics["severity_mae"],
        "silent_sos_caught": metrics["silent_sos_caught"],
        "unanswered": metrics["unanswered"],
        "per_language": metrics["per_language"],
        "department_confusion": metrics["department_confusion"],
        "latency_ms": {
            "median": statistics.median(run.latencies_ms),
            "p95": statistics.quantiles(run.latencies_ms, n=20)[18],
        },
        "llm_calls": sum(stats.calls.values()) if stats else 0,
        "llm_failures": sum(stats.failures.values()) if stats else 0,
        "models": dict(stats.calls) if stats else {},
        "tokens": {"input": sum(stats.input_tokens.values()), "output": sum(stats.output_tokens.values())} if stats else {},
        "cost_inr": cost,
        "cost_per_1000_inr": cost * 1000 / len(rows),
        "notes": run.notes,
    }


def local_gate_curve(rows: Sequence[LabeledReport], answers: Sequence[DecisionResult | None]) -> list[dict[str, float]]:
    """How much the local model could decide alone at each confidence gate, and how well. O(n·g)."""
    from scripts.metrics import triage_correct

    curve = []
    for gate in (0.5, 0.6, 0.7, 0.8, 0.9):
        kept = [(r, a) for r, a in zip(rows, answers, strict=True) if a is not None and a.confidence >= gate]
        curve.append({
            "gate": gate,
            "coverage": len(kept) / len(rows),
            "triage_acc_on_covered": sum(triage_correct(r, a) for r, a in kept) / len(kept) if kept else 0.0,
        })
    return curve


def markdown(report: dict[str, Any]) -> str:
    rows = report["approaches"]
    lines = [
        "# Sanket benchmark",
        "",
        f"Held-out test set: {report['n']} synthetic reports in 5 languages (50 of them never used during development), "
        f"streamed at {REPORTS_PER_SECOND} reports/s. Run {report['run_at']}. Free-tier APIs; cost is list price "
        "for the tokens the providers reported.",
        "",
        "| Approach | Triage acc | Hidden-50 | Emergency P / R / F1 | Dept acc | Severity MAE | Silent SOS | p50 / p95 latency | LLM calls | ₹ per 1,000 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        e = r["emergency"]
        lines.append(
            f"| {r['approach']} | {r['triage_acc']:.3f} | {r['triage_acc_hidden50']:.3f} | "
            f"{e['precision']:.2f} / {e['recall']:.2f} / {e['f1']:.2f} | {r['department_acc']:.3f} | "
            f"{r['severity_mae']:.2f} | {r['silent_sos_caught']} | "
            f"{r['latency_ms']['median']:.0f} / {r['latency_ms']['p95']:.0f} ms | {r['llm_calls']} | "
            f"{r['cost_per_1000_inr']:.2f} |"
        )
    lines += ["", "**Triage accuracy** = emergency call right and, for real emergencies, the right department.", ""]
    lines += ["## Per-language triage accuracy", "", "| Approach | " + " | ".join(sorted(rows[0]["per_language"])) + " |"]
    lines.append("|---|" + "---|" * len(rows[0]["per_language"]))
    for r in rows:
        lines.append(f"| {r['approach']} | " + " | ".join(f"{m['triage_acc']:.2f}" for _, m in sorted(r["per_language"].items())) + " |")
    if report.get("local_gate_curve"):
        lines += ["", "## Local confidence gate (what the local model could decide alone)", "",
                  "| Gate | Share of reports kept local | Triage accuracy on those |", "|---|---|---|"]
        lines += [f"| {c['gate']:.1f} | {c['coverage']:.0%} | {c['triage_acc_on_covered']:.3f} |" for c in report["local_gate_curve"]]
    lines += ["", "## Notes", ""]
    for r in rows:
        for note in r["notes"]:
            lines.append(f"- **{r['approach']}**: {note}")
        if r["unanswered"]:
            lines.append(f"- **{r['approach']}**: {r['unanswered']} reports got no answer (provider limits) and are scored as missed.")
    lines += [f"- {note}" for note in report["notes"]]
    return "\n".join(lines) + "\n"


async def main(selected: list[str], limit: int | None) -> None:
    settings = get_settings()
    rows = load(TEST_PATH)[:limit] if limit else load(TEST_PATH)
    classifier = LocalClassifier.load(settings.local_model_path)
    limiters: dict[str, RateLimiter] = {}
    runs: list[Run] = []
    async with httpx.AsyncClient() as http:

        def fast_decider() -> LLMDecider:
            stats = LLMStats()
            chain = FallbackChain(build_slots(settings, http, limiters=limiters), stats, QUOTA_WAIT_S)
            return LLMDecider(chain, stats, settings.llm_batch_size, settings.llm_batch_wait_ms / 1000, settings.llm_max_concurrency)

        def reasoning_decider() -> LLMDecider:
            # Reasoning models spend output tokens thinking, so they get their own limiters
            # without the Qwen-specific output-per-minute cap and a larger output budget.
            stats = LLMStats()
            timeout = 90.0
            slots: list[ProviderSlot] = []
            if settings.groq_api_key:
                groq = OpenAICompatibleProvider("groq", http, "https://api.groq.com/openai/v1", settings.groq_api_key, REASONING_MODEL, timeout)
                slots.append(ProviderSlot(groq, limiters.setdefault(f"groq/{REASONING_MODEL}", RateLimiter(30, 8000))))
            if settings.gemini_api_key:
                gemini = GeminiProvider(http, settings.gemini_api_key, REASONING_FALLBACK, timeout)
                slots.append(ProviderSlot(gemini, limiters.setdefault(f"gemini/{REASONING_FALLBACK}", RateLimiter(10, 250_000))))
            chain = FallbackChain(slots, stats, QUOTA_WAIT_S)
            return LLMDecider(chain, stats, REASONING_BATCH, 0.3, 1, output_cap_per_item=REASONING_CAP_PER_ITEM)

        plan: dict[str, Callable[[], Awaitable[Run]]] = {
            "keyword": lambda: run_keyword(rows),
            "local": lambda: run_local(rows, classifier),
            "hybrid": lambda: run_hybrid(rows, classifier, fast_decider(), settings.conf_threshold),
            "fast": lambda: run_llm("fast LLM only", rows, fast_decider(), 25),
            "reasoning": lambda: run_llm("reasoning LLM only", rows, reasoning_decider(), REASONING_BATCH),
        }
        for name in selected:
            if name in ("hybrid", "fast", "reasoning") and runs:
                print(f"pausing {QUOTA_RESET_PAUSE_S}s so per-minute quotas refill before {name}")
                await asyncio.sleep(QUOTA_RESET_PAUSE_S)
            started = time.perf_counter()
            run = await plan[name]()
            runs.append(run)
            print(f"{run.name:20s} done in {time.perf_counter() - started:6.1f}s")
    report = {
        "run_at": time.strftime("%Y-%m-%d %H:%M %Z"),
        "n": len(rows),
        "reports_per_second": REPORTS_PER_SECOND,
        "approaches": [summarise(run, rows, settings) for run in runs],
        "local_gate_curve": next((local_gate_curve(rows, r.answers) for r in runs if r.name == "local only"), []),
        "notes": [
            f"Reasoning LLM only uses {REASONING_MODEL} (a reasoning model; {REASONING_FALLBACK} as fallback) in batches "
            f"of {REASONING_BATCH} to fit free-tier limits; one report per call would cost and wait more.",
            f"Each LLM approach starts after a {QUOTA_RESET_PAUSE_S}s pause and may wait up to {QUOTA_WAIT_S:.0f}s for "
            "free-tier quota, so its latency includes throttling, as it would in a real surge on free tiers. "
            "LLM-only approaches re-ask unanswered reports after quotas refill (no fallback of their own); "
            "the hybrid never needs to, because its local answer stands in.",
            "Keyword rules, local only, fast LLM only and reasoning LLM only run without the safety rules; "
            "the hybrid includes them, as Sanket does in production.",
        ],
    }
    JSON_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    MD_PATH.parent.mkdir(exist_ok=True)
    MD_PATH.write_text(markdown(report))
    print(markdown(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approaches", default="keyword,local,hybrid,fast,reasoning")
    parser.add_argument("--limit", type=int, default=None, help="only the first N test rows (smoke runs)")
    args = parser.parse_args()
    asyncio.run(main(args.approaches.split(","), args.limit))
