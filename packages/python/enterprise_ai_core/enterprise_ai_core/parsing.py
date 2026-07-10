from __future__ import annotations

from io import BytesIO
import re
from uuid import uuid4

import fitz
from bs4 import BeautifulSoup
from docx import Document as DocxDocument
from PIL import Image
from pypdf import PdfReader
import pytesseract
from pytesseract import Output, TesseractNotFoundError

from .config import get_settings
from .schemas import RuntimeHealthResponse
from .schemas import CanonicalBlock, CanonicalDocument


def detect_language(text: str) -> str:
    if re.search(r"[ăâđêôơưĂÂĐÊÔƠƯ]", text):
        return "vi"
    if re.search(r"[A-Za-z]", text):
        return "en"
    return "unknown"


def configure_tesseract() -> None:
    settings = get_settings()
    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd


def ocr_runtime_health(service_name: str) -> RuntimeHealthResponse:
    settings = get_settings()
    try:
        configure_tesseract()
        version = str(pytesseract.get_tesseract_version())
        return RuntimeHealthResponse(
            service=service_name,
            runtime="ocr",
            status="ok",
            detail="Tesseract is available",
            metadata={"engine": settings.ocr_engine, "languages": settings.ocr_languages, "version": version},
        )
    except Exception as exc:
        return RuntimeHealthResponse(
            service=service_name,
            runtime="ocr",
            status="error",
            detail=str(exc),
            metadata={"engine": settings.ocr_engine, "languages": settings.ocr_languages},
        )


def extract_text_blocks(
    file_name: str, content_type: str, payload: bytes
) -> tuple[list[CanonicalBlock], bool, bool]:
    settings = get_settings()
    suffix = file_name.lower().rsplit(".", 1)[-1] if "." in file_name else ""
    blocks: list[CanonicalBlock] = []
    ocr_required = False
    ocr_applied = False

    if content_type == "text/plain" or suffix in {"txt", "log"}:
        text = payload.decode("utf-8", errors="ignore")
        blocks = text_to_blocks(text, "paragraph")
    elif suffix in {"md", "markdown"} or content_type in {"text/markdown", "text/x-markdown"}:
        text = payload.decode("utf-8", errors="ignore")
        blocks = markdown_to_blocks(text)
    elif suffix in {"html", "htm"} or content_type == "text/html":
        text = html_to_text(payload.decode("utf-8", errors="ignore"))
        blocks = text_to_blocks(text, "paragraph")
    elif suffix == "pdf" or content_type == "application/pdf":
        blocks = pdf_to_blocks(payload)
        extracted_chars = sum(len(item.text.strip()) for item in blocks)
        ocr_required = extracted_chars < settings.ocr_min_characters
        if ocr_required and settings.ocr_engine == "tesseract":
            ocr_blocks = pdf_to_ocr_blocks(payload)
            if ocr_blocks:
                blocks = ocr_blocks
                ocr_applied = True
    elif suffix == "docx" or (
        content_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        blocks = docx_to_blocks(payload)
    elif suffix in {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"} or content_type.startswith(
        "image/"
    ):
        ocr_required = True
        if settings.ocr_engine == "tesseract":
            blocks = image_to_blocks(payload)
            ocr_applied = bool(blocks)
    else:
        text = payload.decode("utf-8", errors="ignore")
        blocks = text_to_blocks(text, "paragraph")

    return blocks, ocr_required, ocr_applied


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text("\n")


def text_to_blocks(text: str, block_type: str) -> list[CanonicalBlock]:
    blocks: list[CanonicalBlock] = []
    lines = [line.strip() for line in text.splitlines()]
    order_index = 0
    for line in lines:
        if not line:
            continue
        blocks.append(
            CanonicalBlock(
                id=str(uuid4()),
                block_type=block_type,
                order_index=order_index,
                text=line,
            )
        )
        order_index += 1
    return blocks


def markdown_to_blocks(text: str) -> list[CanonicalBlock]:
    blocks: list[CanonicalBlock] = []
    order_index = 0
    current_heading: str | None = None
    current_body: list[str] = []

    def flush_current() -> None:
        nonlocal order_index, current_body
        body = "\n".join(item for item in current_body if item).strip()
        if body:
            blocks.append(
                CanonicalBlock(
                    id=str(uuid4()),
                    block_type="section",
                    order_index=order_index,
                    heading=current_heading,
                    text=body,
                )
            )
            order_index += 1
        current_body = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            flush_current()
            current_heading = line.lstrip("#").strip()
        else:
            current_body.append(line)

    flush_current()
    if not blocks:
        return text_to_blocks(text, "paragraph")
    return blocks


def pdf_to_blocks(payload: bytes) -> list[CanonicalBlock]:
    blocks: list[CanonicalBlock] = []
    reader = PdfReader(BytesIO(payload))
    for page_index, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        blocks.append(
            CanonicalBlock(
                id=str(uuid4()),
                block_type="page",
                order_index=page_index,
                heading=f"Page {page_index + 1}",
                text=text,
                page_start=page_index + 1,
                page_end=page_index + 1,
            )
        )
    return blocks


def pdf_to_ocr_blocks(payload: bytes) -> list[CanonicalBlock]:
    settings = get_settings()
    blocks: list[CanonicalBlock] = []
    document = fitz.open(stream=payload, filetype="pdf")
    scale = settings.ocr_render_dpi / 72
    matrix = fitz.Matrix(scale, scale)

    for page_index, page in enumerate(document):
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        image = Image.open(BytesIO(pixmap.tobytes("png")))
        text, confidence = ocr_image(image)
        if not text.strip():
            continue
        blocks.append(
            CanonicalBlock(
                id=str(uuid4()),
                block_type="ocr-page",
                order_index=page_index,
                heading=f"Page {page_index + 1}",
                text=text,
                page_start=page_index + 1,
                page_end=page_index + 1,
                metadata={"ocr_confidence": confidence},
            )
        )
    return blocks


def image_to_blocks(payload: bytes) -> list[CanonicalBlock]:
    image = Image.open(BytesIO(payload))
    text, confidence = ocr_image(image)
    if not text.strip():
        return []
    return [
        CanonicalBlock(
            id=str(uuid4()),
            block_type="ocr-image",
            order_index=0,
            text=text,
            metadata={"ocr_confidence": confidence},
        )
    ]


def ocr_image(image: Image.Image) -> tuple[str, float]:
    settings = get_settings()
    configure_tesseract()
    try:
        data = pytesseract.image_to_data(
            image,
            lang=settings.ocr_languages,
            output_type=Output.DICT,
        )
    except TesseractNotFoundError:
        return "", 0.0

    tokens: list[str] = []
    confidences: list[float] = []
    for raw_text, raw_confidence in zip(data.get("text", []), data.get("conf", []), strict=False):
        text = (raw_text or "").strip()
        if not text:
            continue
        tokens.append(text)
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            confidence = -1
        if confidence >= 0:
            confidences.append(confidence)

    joined_text = " ".join(tokens).strip()
    average_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return joined_text, average_confidence


def docx_to_blocks(payload: bytes) -> list[CanonicalBlock]:
    blocks: list[CanonicalBlock] = []
    document = DocxDocument(BytesIO(payload))
    for index, paragraph in enumerate(document.paragraphs):
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = getattr(paragraph.style, "name", "") or ""
        block_type = "heading" if "Heading" in style_name else "paragraph"
        heading = text if block_type == "heading" else None
        blocks.append(
            CanonicalBlock(
                id=str(uuid4()),
                block_type=block_type,
                order_index=index,
                heading=heading,
                text=text,
            )
        )
    return blocks


def build_canonical_document(
    *,
    document_id: str,
    document_version_id: str,
    tenant_id: str,
    title: str,
    file_name: str,
    content_type: str,
    payload: bytes,
) -> CanonicalDocument:
    blocks, ocr_required, ocr_applied = extract_text_blocks(file_name, content_type, payload)
    plain_text = "\n\n".join(block.text for block in blocks).strip()
    if not plain_text and ocr_required:
        blocks = [
            CanonicalBlock(
                id=str(uuid4()),
                block_type="ocr-placeholder",
                order_index=0,
                text="OCR was required but no text could be extracted.",
                metadata={"ocr_status": "failed_or_unavailable"},
            )
        ]
        plain_text = blocks[0].text
    return CanonicalDocument(
        document_id=document_id,
        document_version_id=document_version_id,
        tenant_id=tenant_id,
        title=title,
        source_format=file_name.rsplit(".", 1)[-1].lower() if "." in file_name else content_type,
        language=detect_language(plain_text),
        ocr_required=ocr_required,
        ocr_applied=ocr_applied,
        plain_text=plain_text,
        blocks=blocks,
    )
