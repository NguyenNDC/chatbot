from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


INSTRUCT_DIR = Path(__file__).resolve().parent / "instruct"


@dataclass(frozen=True)
class QueryRoute:
    """Deterministic query plan used by retrieval and answer generation."""

    intent: str
    retrieval_strategy: tuple[str, ...]
    response_policy: str
    include_graph: bool = True
    need_full_text: bool = False
    max_context_chars: int = 8_000
    confidence: float = 0.65

    @property
    def instruct_name(self) -> str:
        return self.intent

    def as_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent,
            "instruct": self.instruct_name,
            "retrieval_strategy": list(self.retrieval_strategy),
            "response_policy": self.response_policy,
            "include_graph": self.include_graph,
            "need_full_text": self.need_full_text,
            "max_context_chars": self.max_context_chars,
            "route_confidence": self.confidence,
        }


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    without_marks = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", without_marks).split())


def _contains(text: str, *terms: str) -> bool:
    return any(term in text for term in terms)


def classify_query(question: str, query_mode: str = "auto") -> QueryRoute:
    """Classify a question into an instruct and retrieval strategy.

    Routing is intentionally deterministic and cheap. It can later be replaced by
    an LLM classifier without changing the QueryRoute contract.
    """

    explicit = (query_mode or "auto").strip().lower()
    if explicit != "auto":
        return _route_for_intent(explicit, confidence=1.0)

    text = _normalize(question)
    ordered_rules = (
        ("compare", ("so sanh", "khac nhau", "giong nhau", "doi chieu")),
        ("temporal", ("hieu luc", "con hieu luc", "het hieu luc", "ngay co hieu luc", "thoi diem")),
        ("quote", ("trich dan nguyen van", "trich nguyen van", "nguyen van dieu", "dieu khoan nguyen van")),
        ("document_review", ("ra soat van ban", "kiem tra van ban", "kiem tra chinh ta", "kiem tra ngu nghia")),
        ("procedure", ("quy trinh", "cac buoc", "trinh tu thuc hien", "thu tuc thuc hien")),
        ("conditions", ("dieu kien", "ho so can", "can nhung gi", "yeu cau de duoc")),
        ("scope", ("doi tuong ap dung", "ap dung cho ai", "pham vi ap dung", "don vi nao")),
        ("permission", ("duoc phep", "co duoc", "co duoc lam", "quyen han", "co the thuc hien")),
        ("penalty", ("muc phat", "xu phat", "phat bao nhieu", "hanh vi vi pham")),
        ("statistics", ("thong ke", "phan tich so lieu", "bao nhieu", "so luong")),
        ("error_lookup", ("ma loi", "error code", "loi gi", "nguyen nhan loi", "khac phuc loi")),
        ("summary", ("tom tat", "tom luoc", "tong quan", "noi dung chinh")),
        ("specific_regulation", ("van ban nao", "quy dinh nao", "dieu nao", "can cu phap ly", "theo nghi dinh", "theo thong tu")),
        ("exact_lookup", ("chinh xac", "liet ke", "cu the", "ten ai", "ngay nao")),
    )
    for intent, terms in ordered_rules:
        if _contains(text, *terms):
            return _route_for_intent(intent, confidence=0.92)
    return _route_for_intent("lookup", confidence=0.65)


def _route_for_intent(intent: str, confidence: float) -> QueryRoute:
    routes: dict[str, QueryRoute] = {
        "lookup": QueryRoute(
            intent="lookup",
            retrieval_strategy=("vector", "lexical", "graph"),
            response_policy="grounded_lookup",
        ),
        "summary": QueryRoute(
            intent="summary",
            retrieval_strategy=("document_title", "vector", "lexical"),
            response_policy="structured_summary",
            include_graph=False,
            need_full_text=True,
            max_context_chars=14_000,
        ),
        "compare": QueryRoute(
            intent="compare",
            retrieval_strategy=("vector", "lexical", "graph"),
            response_policy="symmetric_comparison",
            max_context_chars=14_000,
        ),
        "temporal": QueryRoute(
            intent="temporal",
            retrieval_strategy=("document_title", "lexical", "vector", "effective_version"),
            response_policy="effective_date_and_conflict",
            include_graph=False,
            need_full_text=True,
            max_context_chars=16_000,
        ),
        "exact_lookup": QueryRoute(
            intent="exact_lookup",
            retrieval_strategy=("document_title", "lexical", "vector"),
            response_policy="exact_fact_only",
            include_graph=False,
            need_full_text=True,
            max_context_chars=18_000,
        ),
        "specific_regulation": QueryRoute(
            intent="specific_regulation",
            retrieval_strategy=("document_title", "metadata", "lexical", "vector"),
            response_policy="regulation_and_citation",
            include_graph=False,
            max_context_chars=12_000,
        ),
        "conditions": QueryRoute(
            intent="conditions",
            retrieval_strategy=("lexical", "vector", "graph"),
            response_policy="conditions_checklist",
            max_context_chars=12_000,
        ),
        "procedure": QueryRoute(
            intent="procedure",
            retrieval_strategy=("lexical", "vector", "graph"),
            response_policy="ordered_procedure",
            max_context_chars=14_000,
        ),
        "scope": QueryRoute(
            intent="scope",
            retrieval_strategy=("lexical", "vector", "graph"),
            response_policy="scope_and_subjects",
            max_context_chars=12_000,
        ),
        "permission": QueryRoute(
            intent="permission",
            retrieval_strategy=("lexical", "vector", "graph"),
            response_policy="permission_and_exceptions",
            max_context_chars=14_000,
        ),
        "penalty": QueryRoute(
            intent="penalty",
            retrieval_strategy=("lexical", "vector", "graph"),
            response_policy="penalty_with_qualifiers",
            max_context_chars=14_000,
        ),
        "quote": QueryRoute(
            intent="quote",
            retrieval_strategy=("document_title", "lexical"),
            response_policy="verbatim_quote_only",
            include_graph=False,
            need_full_text=True,
            max_context_chars=20_000,
        ),
        "document_review": QueryRoute(
            intent="document_review",
            retrieval_strategy=("document_title", "lexical", "vector"),
            response_policy="document_review_findings",
            include_graph=False,
            need_full_text=True,
            max_context_chars=30_000,
        ),
        "statistics": QueryRoute(
            intent="statistics",
            retrieval_strategy=("lexical", "vector"),
            response_policy="number_and_scope_verification",
            include_graph=False,
            need_full_text=True,
            max_context_chars=20_000,
        ),
        "error_lookup": QueryRoute(
            intent="error_lookup",
            retrieval_strategy=("lexical", "vector"),
            response_policy="error_cause_and_fix",
            include_graph=False,
            max_context_chars=10_000,
        ),
    }
    route = routes.get(intent, routes["lookup"])
    return QueryRoute(
        intent=route.intent,
        retrieval_strategy=route.retrieval_strategy,
        response_policy=route.response_policy,
        include_graph=route.include_graph,
        need_full_text=route.need_full_text,
        max_context_chars=route.max_context_chars,
        confidence=confidence,
    )


def load_route_instruction(intent: str) -> str:
    """Load an intent-specific instruction from the shared instruct directory."""

    safe_intent = re.sub(r"[^a-z0-9_-]", "", (intent or "lookup").lower()) or "lookup"
    path = INSTRUCT_DIR / f"{safe_intent}.md"
    try:
        content = path.read_text(encoding="utf-8").strip()
        if content:
            return content
    except OSError:
        pass
    return load_route_instruction("lookup") if safe_intent != "lookup" else (
        "Trả lời chỉ từ bằng chứng đã truy xuất. Nếu thiếu bằng chứng, nói rõ không tìm thấy. "
        "Luôn kèm nguồn hỗ trợ cho các kết luận quan trọng."
    )
