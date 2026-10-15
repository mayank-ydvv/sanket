"""System 1 local classifier: one shared TF-IDF feature space, three LogisticRegression heads.

Char 2–5 grams (word-boundary aware) absorb typos, romanised Hindi spelling drift
and Indic scripts; word 1–2 grams add phrase cues. The feature union is fitted
once and shared by the emergency, department and severity heads.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion

from app.models import REVIEW_BELOW_CONF, Decision, DecisionResult

MODEL_VERSION = "local-v1"
# Splits on whitespace and punctuation (incl. the Devanagari danda) but keeps
# combining vowel signs inside tokens, which the default \w pattern would cut.
TOKEN_PATTERN = r"[^\s.,!?;:()\"'।|/\-]+"
ALERT_SEVERITY = 4


def build_features() -> FeatureUnion:
    """Unfitted shared feature union (~50k features in total)."""
    common = {"sublinear_tf": True, "min_df": 2, "lowercase": True, "dtype": np.float32}
    return FeatureUnion(
        [
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), max_features=40_000, **common)),
            (
                "word",
                TfidfVectorizer(
                    analyzer="word",
                    ngram_range=(1, 2),
                    token_pattern=TOKEN_PATTERN,
                    max_features=10_000,
                    **common,
                ),
            ),
        ]
    )


def _head() -> LogisticRegression:
    return LogisticRegression(C=10.0, max_iter=3000, class_weight="balanced")


@dataclass(frozen=True)
class LocalModel:
    features: FeatureUnion
    emergency: LogisticRegression
    department: LogisticRegression
    severity: LogisticRegression
    version: str = MODEL_VERSION


def fit(
    texts: Sequence[str],
    is_emergency: Sequence[bool],
    departments: Sequence[str],
    severities: Sequence[int],
) -> LocalModel:
    """Fit features once, then the three heads on the same matrix. O(n·L + heads)."""
    features = build_features()
    x = features.fit_transform(texts)
    return LocalModel(
        features=features,
        emergency=_head().fit(x, np.asarray(is_emergency, dtype=bool)),
        department=_head().fit(x, list(departments)),
        severity=_head().fit(x, np.asarray(severities, dtype=int)),
    )


class LocalClassifier:
    """Batched inference wrapper. CPU-bound: call from a worker thread."""

    def __init__(self, model: LocalModel) -> None:
        self.model = model
        self._emergency_col = int(np.flatnonzero(model.emergency.classes_)[0])

    @classmethod
    def load(cls, path: Path) -> Self:
        """Load a trusted artifact produced by ``scripts/train_local.py``."""
        return cls(joblib.load(path))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.model, path, compress=3)

    def predict_batch(self, texts: Sequence[str]) -> list[DecisionResult]:
        """Decide a batch of texts. O(n·L) vectorisation done once, then O(n·nnz·k) per head.

        Confidence per head is its max class probability; the result confidence is
        the weaker of the emergency and department heads.
        """
        if not texts:
            return []
        m = self.model
        x = m.features.transform(texts)
        p_emergency = m.emergency.predict_proba(x)[:, self._emergency_col]
        dept_proba = m.department.predict_proba(x)
        sev_proba = m.severity.predict_proba(x)
        dept_idx = dept_proba.argmax(axis=1)
        sev_idx = sev_proba.argmax(axis=1)
        results: list[DecisionResult] = []
        for i in range(len(texts)):
            prob = float(p_emergency[i])
            is_emergency = prob >= 0.5
            severity = int(m.severity.classes_[sev_idx[i]])
            decision = Decision(
                is_emergency=is_emergency,
                emergency_prob=prob,
                department=str(m.department.classes_[dept_idx[i]]),  # type: ignore[arg-type]
                department_conf=float(dept_proba[i, dept_idx[i]]),
                severity=severity,
                alert_now=is_emergency and severity >= ALERT_SEVERITY,
            )
            needs_review = decision.confidence < REVIEW_BELOW_CONF
            if needs_review:
                decision = decision.model_copy(update={"needs_human_review": True})
            results.append(
                DecisionResult(
                    decision=decision, source="local", confidence=decision.confidence, model=m.version
                )
            )
        return results
