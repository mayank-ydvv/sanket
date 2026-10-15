"""Train the System 1 local classifier and report test accuracy and latency.

Run from ``backend/``: ``python -m scripts.train_local``. Evaluates on the visible
test rows only; the hidden rows are reserved for the final benchmark.
"""

import json
import statistics
import time
from collections.abc import Sequence

from app.config import get_settings
from app.decision.local import LocalClassifier, fit
from scripts.dataset import TEST_PATH, TRAIN_PATH, load
from scripts.metrics import evaluate, format_summary

BATCH = 25


def measure_latency(classifier: LocalClassifier, texts: Sequence[str]) -> dict[str, float]:
    """Per-report latency when batched (BATCH) and when called one at a time."""
    classifier.predict_batch(texts[:BATCH])  # warm-up
    start = time.perf_counter()
    for i in range(0, len(texts), BATCH):
        classifier.predict_batch(texts[i : i + BATCH])
    batched_ms = (time.perf_counter() - start) * 1000 / len(texts)
    singles = []
    for text in texts[:100]:
        t0 = time.perf_counter()
        classifier.predict_batch([text])
        singles.append((time.perf_counter() - t0) * 1000)
    return {"batched_ms_per_report": batched_ms, "single_median_ms": statistics.median(singles)}


def main() -> None:
    settings = get_settings()
    train = load(TRAIN_PATH)
    test = load(TEST_PATH, include_hidden=False)
    t0 = time.perf_counter()
    model = fit(
        [r.text for r in train],
        [r.is_emergency for r in train],
        [r.department for r in train],
        [r.severity for r in train],
    )
    fit_s = time.perf_counter() - t0
    classifier = LocalClassifier(model)
    classifier.save(settings.local_model_path)

    texts = [r.text for r in test]
    metrics = evaluate(test, classifier.predict_batch(texts))
    metrics["latency"] = measure_latency(classifier, texts)
    metrics["model_version"] = model.version
    metrics["n_features"] = sum(len(t.vocabulary_) for _, t in model.features.transformer_list)
    settings.local_model_path.with_suffix(".metrics.json").write_text(json.dumps(metrics, indent=2))

    print(f"trained {model.version} on {len(train)} rows in {fit_s:.2f}s ({metrics['n_features']} features)")
    print(f"saved {settings.local_model_path}")
    print(f"test (visible, n={len(test)}):")
    print(format_summary(metrics))
    lat = metrics["latency"]
    print(
        f"latency: {lat['batched_ms_per_report']:.3f} ms/report batched x{BATCH}, "
        f"{lat['single_median_ms']:.2f} ms single"
    )


if __name__ == "__main__":
    main()
