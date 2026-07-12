from __future__ import annotations

import hashlib
import math
import os
import re
import unicodedata
from typing import Any

from .config import get_settings
from .schemas import RuntimeHealthResponse

_EMBEDDING_PROVIDER_PID: int | None = None
_EMBEDDING_PROVIDER_INSTANCE: "BaseEmbeddingProvider | None" = None


class BaseEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self.embed(texts)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed(texts)


class HashEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = self._tokenize(text)
        if not tokens:
            return vector
        for token in tokens:
            self._add_feature(vector, f"tok:{token}", 1.0)
        for left, right in zip(tokens, tokens[1:]):
            self._add_feature(vector, f"bg:{left}_{right}", 0.7)
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def _tokenize(self, text: str) -> list[str]:
        normalized = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
        without_marks = "".join(
            char for char in normalized if unicodedata.category(char) != "Mn"
        )
        cleaned = " ".join(re.sub(r"[^a-z0-9\s]", " ", without_marks).split())
        return cleaned.split()

    def _add_feature(self, vector: list[float], feature: str, weight: float) -> None:
        digest = hashlib.sha256(feature.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % self.dimension
        vector[index] += weight


class BgeM3EmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self) -> None:
        try:
            import torch
            from FlagEmbedding import BGEM3FlagModel  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "BGE-M3 provider requires FlagEmbedding. Install it before enabling EMBEDDING_PROVIDER=bge-m3."
            ) from exc

        settings = get_settings()
        self.device = resolve_torch_device(torch, settings.embedding_device)
        self.use_fp16 = bool(settings.embedding_use_fp16 and self.device.startswith("cuda"))
        try:
            self.model = BGEM3FlagModel(
                settings.embedding_model_name,
                use_fp16=self.use_fp16,
                device=self.device,
            )
        except TypeError:
            self.model = BGEM3FlagModel(
                settings.embedding_model_name,
                use_fp16=self.use_fp16,
            )
            model_handle = getattr(self.model, "model", None)
            if model_handle is not None and hasattr(model_handle, "to"):
                model_handle.to(self.device)
            setattr(self.model, "device", self.device)

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = self.model.encode(texts, batch_size=min(8, len(texts)), max_length=2048)
        return [list(item) for item in result["dense_vecs"]]


class E5EmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self) -> None:
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "E5 provider requires transformers and torch. Install requirements/ml.txt before enabling EMBEDDING_PROVIDER=e5."
            ) from exc

        settings = get_settings()
        self.torch = torch
        self.device = resolve_torch_device(torch, settings.embedding_device)
        self.use_fp16 = bool(settings.embedding_use_fp16 and self.device.startswith("cuda"))
        self.target_dimension = settings.embedding_dimension
        self.model_name = settings.embedding_model_name
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        model_kwargs: dict[str, Any] = {}
        if self.use_fp16:
            model_kwargs["torch_dtype"] = torch.float16
        self.model = AutoModel.from_pretrained(self.model_name, **model_kwargs)
        self.model.to(self.device)
        self.model.eval()
        self.max_length = 512

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self._embed_prefixed(texts, prefix="query: ")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed_prefixed(texts, prefix="passage: ")

    def _embed_prefixed(self, texts: list[str], prefix: str) -> list[list[float]]:
        if not texts:
            return []

        vectors: list[list[float]] = []
        prepared = [self._ensure_prefix(text, prefix) for text in texts]
        batch_size = min(16, len(prepared))
        for start in range(0, len(prepared), batch_size):
            batch = prepared[start : start + batch_size]
            encoded = self.tokenizer(
                batch,
                max_length=self.max_length,
                padding=True,
                truncation=True,
                return_tensors="pt",
            )
            encoded = {key: value.to(self.device) for key, value in encoded.items()}
            with self.torch.inference_mode():
                outputs = self.model(**encoded)
            pooled = self._average_pool(outputs.last_hidden_state, encoded["attention_mask"])
            normalized = self.torch.nn.functional.normalize(pooled, p=2, dim=1)
            vectors.extend(
                self._pad_vector(row.tolist(), target_dimension=self.target_dimension)
                for row in normalized.cpu()
            )
        return vectors

    def _average_pool(self, last_hidden_state: Any, attention_mask: Any) -> Any:
        masked = last_hidden_state.masked_fill(~attention_mask[..., None].bool(), 0.0)
        return masked.sum(dim=1) / attention_mask.sum(dim=1)[..., None]

    def _ensure_prefix(self, text: str, prefix: str) -> str:
        normalized = " ".join(text.split())
        lowered = normalized.lower()
        if lowered.startswith("query:") or lowered.startswith("passage:"):
            return normalized
        return f"{prefix}{normalized}"

    def _pad_vector(self, vector: list[float], target_dimension: int) -> list[float]:
        if len(vector) > target_dimension:
            raise ValueError(
                f"Embedding dimension {len(vector)} exceeds configured target dimension {target_dimension}."
            )
        if len(vector) == target_dimension:
            return vector
        return [*vector, *([0.0] * (target_dimension - len(vector)))]


def embedding_runtime_health(service_name: str) -> RuntimeHealthResponse:
    settings = get_settings()
    try:
        provider = get_embedding_provider()
        sample = provider.embed_queries(["runtime healthcheck"])
        dimension = len(sample[0]) if sample else 0
        metadata = {
            "provider": settings.embedding_provider,
            "model_name": settings.embedding_model_name,
            "dimension": dimension,
        }
        if hasattr(provider, "device"):
            metadata["device"] = getattr(provider, "device")
        if hasattr(provider, "use_fp16"):
            metadata["fp16"] = bool(getattr(provider, "use_fp16"))
        return RuntimeHealthResponse(
            service=service_name,
            runtime="embedding",
            status="ok",
            detail=f"{provider.__class__.__name__} loaded successfully",
            metadata=metadata,
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
                "requested_device": settings.embedding_device,
                "requested_fp16": settings.embedding_use_fp16,
            },
        )


def resolve_torch_device(torch_module: Any, requested_device: str) -> str:
    normalized = (requested_device or "auto").strip().lower()
    if normalized == "auto":
        return "cuda" if torch_module.cuda.is_available() else "cpu"
    if normalized.startswith("cuda") and not torch_module.cuda.is_available():
        raise RuntimeError("EMBEDDING_DEVICE is set to CUDA but torch.cuda.is_available() is false.")
    return normalized


def get_embedding_provider() -> BaseEmbeddingProvider:
    global _EMBEDDING_PROVIDER_INSTANCE, _EMBEDDING_PROVIDER_PID
    current_pid = os.getpid()
    if _EMBEDDING_PROVIDER_INSTANCE is not None and _EMBEDDING_PROVIDER_PID == current_pid:
        return _EMBEDDING_PROVIDER_INSTANCE

    settings = get_settings()
    if settings.embedding_provider == "bge-m3":
        provider: BaseEmbeddingProvider = BgeM3EmbeddingProvider()
    elif settings.embedding_provider in {"e5", "multilingual-e5"}:
        provider = E5EmbeddingProvider()
    else:
        provider = HashEmbeddingProvider(settings.embedding_dimension)

    _EMBEDDING_PROVIDER_INSTANCE = provider
    _EMBEDDING_PROVIDER_PID = current_pid
    return provider
