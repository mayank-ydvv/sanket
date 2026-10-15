"""Schema and loader for the labelled synthetic datasets in ``data/*.jsonl``."""

from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import Department

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
TRAIN_PATH = DATA_DIR / "train.jsonl"
TEST_PATH = DATA_DIR / "test.jsonl"

Category = Literal["emergency", "non_urgent", "prank"]


class LabeledReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    text: str
    language: Literal["en", "hinglish", "hi", "ta", "bn"]
    category: Category
    is_emergency: bool
    department: Department
    severity: int = Field(ge=1, le=5)
    location_text: str | None
    silent_sos: bool = False
    hard: str | None = None
    hidden: bool = False


def iter_jsonl(path: Path) -> Iterator[LabeledReport]:
    """Stream validated rows. O(n·L)."""
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield LabeledReport.model_validate_json(line)


def load(path: Path, *, include_hidden: bool = True) -> list[LabeledReport]:
    return [row for row in iter_jsonl(path) if include_hidden or not row.hidden]
