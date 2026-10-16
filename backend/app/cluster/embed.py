"""Sentence embeddings for clustering (multilingual MiniLM, unit-normalised).

The embedded text is prefixed with canonical English tags (department and
hazards from the decision). MiniLM aligns Devanagari Hindi with English well but
romanised Hinglish poorly; shared tags pull duplicates in different languages
together without overriding what the text says.
"""

from collections.abc import Sequence
from typing import Protocol

import numpy as np
import numpy.typing as npt

from app.models import Decision

Matrix = npt.NDArray[np.float32]


class Embedder(Protocol):
    dim: int

    def encode(self, texts: Sequence[str]) -> Matrix: ...


class SentenceEmbedder:
    """CPU-bound: call ``encode`` from a worker thread with whole batches."""

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name, device="cpu")
        self.dim = int(self._model.get_embedding_dimension() or 384)

    def encode(self, texts: Sequence[str]) -> Matrix:
        """Unit vectors, one row per text. O(n·L) model passes, batched."""
        vectors = self._model.encode(
            list(texts), batch_size=64, normalize_embeddings=True, convert_to_numpy=True
        )
        return np.asarray(vectors, dtype=np.float32)


class HashingEmbedder:
    """Model-free fallback (and test double): hashed char 2–4 grams, unit-normalised.

    Used when the sentence model is disabled or cannot load, so clustering degrades
    to lexical similarity instead of failing. O(n·L).
    """

    def __init__(self, dim: int = 1024) -> None:
        from sklearn.feature_extraction.text import HashingVectorizer

        self.dim = dim
        self._vectorizer = HashingVectorizer(
            analyzer="char_wb", ngram_range=(2, 4), n_features=dim, alternate_sign=False, norm="l2"
        )

    def encode(self, texts: Sequence[str]) -> Matrix:
        return np.asarray(self._vectorizer.transform(list(texts)).toarray(), dtype=np.float32)


def embedding_text(text: str, decision: Decision) -> str:
    """Text actually embedded for clustering. O(L)."""
    tags = " ".join([decision.department, *decision.hazards]).replace("_", " ")
    return f"{tags}: {text}"
