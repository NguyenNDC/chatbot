from __future__ import annotations

import hashlib
import math
from functools import lru_cache

from .config import get_settings
from .schemas import RuntimeHealthResponse


class BaseEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class HashEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = text.lower().split()
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class BgeM3EmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self) -> None:
        try:
            from FlagEmbedding import BGEM3FlagModel  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "BGE-M3 provider requires FlagEmbedding. Install it before enabling EMBEDDING_PROVIDER=bge-m3."
            ) from exc

        settings = get_settings()
        self.model = BGEM3FlagModel(settings.embedding_model_name, use_fp16=False)

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = self.model.encode(texts, batch_size=min(8, len(texts)), max_length=2048)
        return [list(item) for item in result["dense_vecs"]]


def embedding_runtime_health(service_name: str) -> RuntimeHealthResponse:
    settings = get_settings()
    try:
        provider = get_embedding_provider()
        sample = provider.embed(["runtime healthcheck"])
        dimension = len(sample[0]) if sample else 0
        return RuntimeHealthResponse(
            service=service_name,
            runtime="embedding",
            status="ok",
            detail=f"{provider.__class__.__name__} loaded successfully",
            metadata={
                "provider": settings.embedding_provider,
                "model_name": settings.embedding_model_name,
                "dimension": dimension,
            },
        )
    except Exception as exc:
        return RuntimeHealthResponse(
            service=service_name,
            runtime="embedding",
            status="error",
            detail=str(exc),
            metadata={
                "provider": settings.embedding_provider,
                "model_name": settings.embedding_model_name,
            },
        )


@lru_cache
def get_embedding_provider() -> BaseEmbeddingProvider:
    settings = get_settings()
    if settings.embedding_provider == "bge-m3":
        return BgeM3EmbeddingProvider()
    return HashEmbeddingProvider(settings.embedding_dimension)
