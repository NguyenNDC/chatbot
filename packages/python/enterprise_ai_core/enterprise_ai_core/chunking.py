from __future__ import annotations

import hashlib
from uuid import uuid4

from .config import get_settings
from .schemas import CanonicalBlock, CanonicalDocument, ChunkItem


def estimate_tokens(text: str) -> int:
    return max(1, len(text.split()))


def _slice_with_overlap(words: list[str], target: int, overlap: int) -> list[str]:
    step = max(1, target - overlap)
    chunks: list[str] = []
    for start in range(0, len(words), step):
        segment = words[start : start + target]
        if not segment:
            continue
        chunks.append(" ".join(segment))
        if start + target >= len(words):
            break
    return chunks


def blocks_to_chunks(document: CanonicalDocument) -> list[ChunkItem]:
    settings = get_settings()
    chunks: list[ChunkItem] = []
    chunk_index = 0

    for block in document.blocks:
        section_name = block.heading or block.block_type
        token_estimate = estimate_tokens(block.text)
        if token_estimate <= settings.chunk_target_tokens:
            chunks.append(
                make_chunk(
                    document=document,
                    chunk_index=chunk_index,
                    section_name=section_name,
                    block=block,
                    content=block.text,
                )
            )
            chunk_index += 1
            continue

        for piece in _slice_with_overlap(
            block.text.split(),
            settings.chunk_target_tokens,
            settings.chunk_overlap_tokens,
        ):
            chunks.append(
                make_chunk(
                    document=document,
                    chunk_index=chunk_index,
                    section_name=section_name,
                    block=block,
                    content=piece,
                )
            )
            chunk_index += 1

    if not chunks and document.plain_text:
        synthetic_block = CanonicalBlock(
            id=str(uuid4()),
            block_type="body",
            order_index=0,
            text=document.plain_text,
        )
        return blocks_to_chunks(
            document.model_copy(update={"blocks": [synthetic_block]})
        )

    return chunks


def make_chunk(
    *,
    document: CanonicalDocument,
    chunk_index: int,
    section_name: str,
    block: CanonicalBlock,
    content: str,
) -> ChunkItem:
    return ChunkItem(
        id=str(uuid4()),
        document_id=document.document_id,
        document_version_id=document.document_version_id,
        tenant_id=document.tenant_id,
        chunk_index=chunk_index,
        section_name=section_name,
        page_start=block.page_start,
        page_end=block.page_end,
        content=content,
        token_estimate=estimate_tokens(content),
        metadata={
            "source_block_id": block.id,
            "block_type": block.block_type,
            "language": document.language,
            "ocr_required": document.ocr_required,
        },
    )


def chunk_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
