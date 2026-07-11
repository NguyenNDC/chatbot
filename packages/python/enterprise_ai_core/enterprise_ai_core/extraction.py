from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
from typing import Callable
from uuid import uuid4

from .config import get_settings
from .openrouter import OpenRouterClient
from .schemas import ChunkExtractionPayload


EXTRACTION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "chunk_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "summary": {"type": "string"},
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string"},
                            "canonical_name": {"type": "string"},
                            "entity_type": {"type": "string"},
                            "aliases": {"type": "array", "items": {"type": "string"}},
                            "confidence": {"type": "number"},
                            "attributes": {"type": "object", "additionalProperties": True},
                        },
                        "required": [
                            "id",
                            "canonical_name",
                            "entity_type",
                            "aliases",
                            "confidence",
                            "attributes",
                        ],
                    },
                },
                "relations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string"},
                            "source_entity_id": {"type": "string"},
                            "target_entity_id": {"type": "string"},
                            "relation_type": {"type": "string"},
                            "confidence": {"type": "number"},
                            "evidence": {"type": ["string", "null"]},
                        },
                        "required": [
                            "id",
                            "source_entity_id",
                            "target_entity_id",
                            "relation_type",
                            "confidence",
                            "evidence",
                        ],
                    },
                },
            },
            "required": ["summary", "entities", "relations"],
        },
    },
}


def entity_key(name: str, entity_type: str) -> str:
    normalized = re.sub(r"\s+", " ", name.strip().lower())
    return f"{entity_type.lower()}::{normalized}"


def run_chunk_extraction(
    *,
    client: OpenRouterClient,
    model_name: str,
    tenant_id: str,
    document_id: str,
    chunk_id: str,
    content: str,
    section_name: str,
) -> ChunkExtractionPayload:
    messages = [
        {
            "role": "system",
            "content": (
                "You extract entities and relations from enterprise documents. "
                "Return only grounded facts supported by the provided chunk. "
                "Use short canonical names, keep relation types uppercase with underscores, "
                "and do not invent entities beyond the source text."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Tenant: {tenant_id}\n"
                f"Document: {document_id}\n"
                f"Section: {section_name}\n"
                f"Chunk ID: {chunk_id}\n\n"
                "Extract entities, relations, and a short summary from the chunk below.\n"
                "Only include relations when both source and target entities are explicitly supported.\n\n"
                f"Chunk:\n{content}"
            ),
        },
    ]
    result = client.chat_completion(
        model=model_name,
        messages=messages,
        response_format=EXTRACTION_RESPONSE_FORMAT,
        temperature=0.0,
        max_tokens=1200,
    )
    payload = result["content"]
    if isinstance(payload, str):
        payload = json.loads(payload)

    normalized_entities = []
    for item in payload.get("entities", []):
        normalized_entities.append(
            {
                **item,
                "id": item.get("id") or str(uuid4()),
                "canonical_name": item["canonical_name"].strip(),
                "entity_type": item["entity_type"].strip() or "UNKNOWN",
            }
        )

    normalized_relations = []
    for item in payload.get("relations", []):
        normalized_relations.append(
            {
                **item,
                "id": item.get("id") or str(uuid4()),
                "relation_type": item["relation_type"].strip().upper().replace(" ", "_"),
            }
        )

    return ChunkExtractionPayload.model_validate(
        {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "document_chunk_id": chunk_id,
            "summary": payload.get("summary", ""),
            "entities": normalized_entities,
            "relations": normalized_relations,
        }
    )


def clone_extraction_for_chunk(
    payload: ChunkExtractionPayload,
    *,
    chunk_id: str,
) -> ChunkExtractionPayload:
    return payload.model_copy(
        update={
            "document_chunk_id": chunk_id,
            "entities": [
                entity.model_copy(update={"id": entity.id or str(uuid4())})
                for entity in payload.entities
            ],
            "relations": [
                relation.model_copy(update={"id": relation.id or str(uuid4())})
                for relation in payload.relations
            ],
        }
    )


def run_parallel_chunk_extractions(
    *,
    client: OpenRouterClient,
    model_name: str,
    tenant_id: str,
    document_id: str,
    chunk_requests: list[dict[str, str]],
    progress_callback: Callable[[int, int], None] | None = None,
    result_callback: Callable[[ChunkExtractionPayload, int, int], None] | None = None,
) -> list[ChunkExtractionPayload]:
    if not chunk_requests:
        return []

    settings = get_settings()
    max_workers = max(1, min(settings.graph_extract_max_concurrency, len(chunk_requests)))
    ordered_results: list[ChunkExtractionPayload | None] = [None] * len(chunk_requests)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                run_chunk_extraction,
                client=client,
                model_name=model_name,
                tenant_id=tenant_id,
                document_id=document_id,
                chunk_id=request["chunk_id"],
                content=request["content"],
                section_name=request["section_name"],
            ): index
            for index, request in enumerate(chunk_requests)
        }

        completed = 0
        for future in as_completed(future_map):
            index = future_map[future]
            payload = future.result()
            ordered_results[index] = payload
            completed += 1
            if result_callback is not None:
                result_callback(payload, completed, len(chunk_requests))
            if progress_callback is not None:
                progress_callback(completed, len(chunk_requests))

    return [item for item in ordered_results if item is not None]

