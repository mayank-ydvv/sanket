import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.decision.local import LocalClassifier
from app.main import create_app
from scripts.dataset import TEST_PATH, load
from tests.conftest import receive_event

EASY = [
    ("Marina beach pe building mein aag lagi hai, dhuaan nikal raha", "fire"),
    ("Velachery main road पर दो लोग चाकू लेकर लड़ रहे हैं, मारपीट हो रही है", "police"),
    ("papa ko seene mein dard, ambulance chahiye", "medical"),
    ("বাড়িতে জল ঢুকেছে, বন্যা, লোকজন ছাদে আটকে", "disaster"),
]


def test_predict_batch_shape_and_types(classifier: LocalClassifier) -> None:
    texts = [t for t, _ in EASY] + ["hello hello testing 123", ""]
    results = classifier.predict_batch(texts)
    assert len(results) == len(texts)
    for result in results:
        assert result.source == "local"
        assert 0.0 <= result.confidence <= 1.0
        assert 1 <= result.decision.severity <= 5
    assert classifier.predict_batch([]) == []


def test_obvious_reports_route_correctly(classifier: LocalClassifier) -> None:
    results = classifier.predict_batch([t for t, _ in EASY])
    for (text, department), result in zip(EASY, results, strict=True):
        assert result.decision.is_emergency, text
        assert result.decision.department == department, text


def test_batched_latency_under_5ms_per_report(classifier: LocalClassifier) -> None:
    texts = [r.text for r in load(TEST_PATH)]
    classifier.predict_batch(texts[:25])
    start = time.perf_counter()
    for i in range(0, len(texts), 25):
        classifier.predict_batch(texts[i : i + 25])
    assert (time.perf_counter() - start) * 1000 / len(texts) < 5.0


def test_save_load_roundtrip(classifier: LocalClassifier, model_path: Path) -> None:
    text = EASY[0][0]
    assert LocalClassifier.load(model_path).predict_batch([text]) == classifier.predict_batch([text])


def test_app_uses_local_model(settings: Settings, model_path: Path) -> None:
    app = create_app(settings.model_copy(update={"local_model_path": model_path}))
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        client.post("/reports", json={"text": EASY[0][0], "channel": "sms"})
        data = receive_event(ws, "report.created")["data"]
    assert data["source"] == "local"
    assert data["decision"]["department"] == "fire"
