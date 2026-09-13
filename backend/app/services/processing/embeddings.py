from functools import lru_cache

import numpy as np

from app.config import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, EMBEDDING_REVISION, EMBEDDING_SPACE


def embedding_text(title: str, body: str) -> str:
    return title + "\n" + " ".join(body.split()[:300])


def validate_vector(vector) -> list[float]:
    array = np.asarray(vector, dtype=np.float32)
    if array.shape != (EMBEDDING_DIMENSIONS,) or not np.isfinite(array).all():
        raise ValueError(f"Expected {EMBEDDING_DIMENSIONS} finite embedding dimensions")
    norm = float(np.linalg.norm(array))
    if norm == 0:
        raise ValueError("Zero embeddings cannot be clustered")
    return (array / norm).tolist()


@lru_cache(maxsize=1)
def load_model():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("Install the local extra: pip install -e '.[local]'") from exc
    # CPU is intentional: the first milestone does not require a GPU or paid API.
    return SentenceTransformer(
        EMBEDDING_MODEL, revision=EMBEDDING_REVISION, device="cpu", trust_remote_code=False
    )


class LocalEmbedder:
    model_name = EMBEDDING_SPACE

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [
            validate_vector(v)
            for v in load_model().encode(
                texts,
                batch_size=32,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        ]
