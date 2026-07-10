from __future__ import annotations

import hashlib
from uuid import uuid4

from .config import get_settings
from .schemas import CanonicalBlock, CanonicalDocument, ChunkItem


def estimate_tokens(text: str) -> int:
    return max(1, len(text.split()))


def _slice_with_overlap(words: list[str], target: int, overlap: int) -> list[tuple[str, int, int]]:
    step = max(1, target - overlap)
    chunks: list[tuple[str, int, int]] = []
    for start in range(0, len(words), step):
        segment = words[start : start + target]
        if not segment:
            continue
        chunks.append((" ".join(segment), start, start + len(segment)))
        if start + target >= len(words):
            break
    return chunks


def blocks_to_chunks(document: CanonicalDocument) -> list[ChunkItem]:
    settings = get_settings()
    chunks: list[ChunkItem] = []
    chunk_index = 0

    for block in document.blocks:
        section_name = (
            block.heading
            or (block.heading_path[-1] if block.heading_path else None)
            or block.block_type
        )
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

        words = block.text.split()
        for piece, word_start, word_end in _slice_with_overlap(
            words,
            settings.chunk_target_tokens,
            settings.chunk_overlap_tokens,
        ):
            relative_start = estimate_char_offset(words, word_start)
            relative_end = estimate_char_offset(words, word_end)
            chunks.append(
                make_chunk(
                    document=document,
                    chunk_index=chunk_index,
                    section_name=section_name,
                    block=block,
                    content=piece,
                    source_offset_start=(
                        block.source_offset_start + relative_start
                        if block.source_offset_start is not None
                        else None
                    ),
                    source_offset_end=(
                        block.source_offset_start + relative_end
                        if block.source_offset_start is not None
                        else None
                    ),
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
        return blocks_to_chunks(document.model_copy(update={"blocks": [synthetic_block]}))

    return chunks


def make_chunk(
    *,
    document: CanonicalDocument,
    chunk_index: int,
    section_name: str,
    block: CanonicalBlock,
    content: str,
    source_offset_start: int | None = None,
    source_offset_end: int | None = None,
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
        source_offset_start=(
            source_offset_start
            if source_offset_start is not None
            else block.source_offset_start
        ),
        source_offset_end=(
            source_offset_end if source_offset_end is not None else block.source_offset_end
        ),
        heading_path=block.heading_path,
        content=content,
        token_estimate=estimate_tokens(content),
        parse_quality_score=block.parse_quality_score or document.parse_quality_score,
        metadata={
            "source_block_id": block.id,
            "block_type": block.block_type,
            "language": document.language,
            "ocr_required": document.ocr_required,
            "ocr_applied": document.ocr_applied,
            "heading_path": block.heading_path,
            "table_id": block.table_id,
            "row_index": block.row_index,
            "cell_index": block.cell_index,
            "parse_quality_score": block.parse_quality_score or document.parse_quality_score,
            "parse_warnings": document.parse_warnings,
        },
    )


def estimate_char_offset(words: list[str], word_index: int) -> int:
    if word_index <= 0:
        return 0
    prefix = " ".join(words[:word_index])
    return len(prefix) + 1


def chunk_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
