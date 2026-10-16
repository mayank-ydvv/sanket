import weakref
from collections import deque
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.decision.local import LocalClassifier, fit
from app.main import create_app
from scripts.dataset import TRAIN_PATH, load

TEST_SALT = "test-salt-0123456789abcdef"


@pytest.fixture(scope="session")
def classifier() -> LocalClassifier:
    rows = load(TRAIN_PATH)
    return LocalClassifier(
        fit(
            [r.text for r in rows],
            [r.is_emergency for r in rows],
            [r.department for r in rows],
            [r.severity for r in rows],
        )
    )


@pytest.fixture(scope="session")
def model_path(classifier: LocalClassifier, tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("model") / "local.joblib"
    classifier.save(path)
    return path


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Isolated from sanket/.env (no real keys, no live LLM calls) and with no trained model."""
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        caller_salt=TEST_SALT,
        db_path=tmp_path / "test.db",
        local_model_path=tmp_path / "missing.joblib",
        ingest_batch_wait_ms=10,
        embedding_backend="hashing",
        geocode_network=False,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


_BUFFERS: "weakref.WeakKeyDictionary[Any, deque[dict[str, Any]]]" = weakref.WeakKeyDictionary()


def receive_event(ws: Any, event_type: str, limit: int = 20) -> dict[str, Any]:
    """Next event of ``event_type`` from the batched stream, skipping others.

    Events that arrive in the same batch are buffered per socket, so two reports
    coalesced into one message are both seen.
    """
    buffer = _BUFFERS.setdefault(ws, deque())
    for _ in range(limit):
        while buffer:
            event = buffer.popleft()
            if event["type"] == event_type:
                return event
        message: dict[str, Any] = ws.receive_json()
        buffer.extend(message["data"] if message["type"] == "batch" else [message])
    raise AssertionError(f"no {event_type} event in {limit} messages")
