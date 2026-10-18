"""Post labelled test reports to a running server and score what comes back.

Run from ``backend/``: ``python -m scripts.post_reports --n 100``. Uses only the
visible test rows. Prints accuracy, lanes, rules fired, latency and LLM call count.
"""

import argparse
import asyncio
import time
from collections import Counter

import httpx

from scripts.dataset import TEST_PATH, LabeledReport, load

POLL_S = 0.1


async def post_all(client: httpx.AsyncClient, rows: list[LabeledReport]) -> dict[str, LabeledReport]:
    async def post(row: LabeledReport) -> tuple[str, LabeledReport]:
        response = await client.post(
            "/reports", json={"text": row.text, "channel": "sms", "caller": f"+9190000{row.id[-5:]}"}
        )
        response.raise_for_status()
        return response.json()["id"], row

    return dict(await asyncio.gather(*(post(r) for r in rows)))


async def main(base_url: str, n: int, timeout_s: float, email: str | None, password: str | None) -> None:
    rows = load(TEST_PATH, include_hidden=False)[:n]
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        if email and password:  # dispatcher routes (/stats, GET /reports) need a session
            (await client.post("/auth/login", json={"email": email, "password": password})).raise_for_status()
        before = (await client.get("/stats")).json()
        start = time.perf_counter()
        by_id = await post_all(client, rows)
        posted_s = time.perf_counter() - start
        while True:
            stats = (await client.get("/stats")).json()
            if stats["reports_decided"] - before["reports_decided"] >= n:
                break
            if time.perf_counter() - start > timeout_s:
                raise SystemExit(f"timed out: {stats['reports_decided'] - before['reports_decided']}/{n} decided")
            await asyncio.sleep(POLL_S)
        done_s = time.perf_counter() - start
        decided = [r for r in (await client.get("/reports", params={"limit": 500})).json() if r["id"] in by_id]

    pairs = [(by_id[r["id"]], r) for r in decided]
    emergencies = [(row, r) for row, r in pairs if row.is_emergency]
    recall = sum(r["decision"]["is_emergency"] for _, r in emergencies) / max(1, len(emergencies))
    emergency_acc = sum(row.is_emergency == r["decision"]["is_emergency"] for row, r in pairs) / len(pairs)
    department_acc = sum(row.department == r["decision"]["department"] for row, r in pairs) / len(pairs)
    sos = [(row, r) for row, r in pairs if row.silent_sos]
    llm_before = (before["llm"] or {}).get("calls", 0)
    llm_after = (stats["llm"] or {}).get("calls", 0)

    print(f"posted {n} reports in {posted_s:.2f}s; all decided after {done_s:.2f}s")
    print(f"emergency acc={emergency_acc:.3f} recall={recall:.3f}  department acc={department_acc:.3f}")
    print(f"silent SOS caught: {sum(r['decision']['silent_sos'] for _, r in sos)}/{len(sos)}")
    print(f"source: {dict(Counter(r['source'] for _, r in pairs))}")
    print(f"lane:   {dict(Counter(r['lane'] for _, r in pairs))}")
    print(f"rules:  {dict(Counter(f.split(':')[0] for _, r in pairs for f in r['flags']))}")
    print(f"LLM calls: {llm_after - llm_before} (chain: {' -> '.join(stats['llm_chain']) or 'none configured'})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--email", help="dispatcher account (needed unless AUTH_REQUIRED=false)")
    parser.add_argument("--password")
    args = parser.parse_args()
    asyncio.run(main(args.base_url, args.n, args.timeout, args.email, args.password))
