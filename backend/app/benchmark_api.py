"""Serves the last benchmark run (written by ``python -m scripts.benchmark``)."""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["benchmark"])
BENCHMARK_PATH = Path(__file__).resolve().parents[1] / "data" / "benchmark.json"


@router.get("/benchmark")
async def benchmark() -> dict[str, Any]:
    if not BENCHMARK_PATH.exists():
        raise HTTPException(404, "no benchmark yet: run `python -m scripts.benchmark`")
    result: dict[str, Any] = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    return result
