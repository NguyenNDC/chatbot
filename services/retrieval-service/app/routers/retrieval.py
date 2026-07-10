from fastapi import APIRouter

from enterprise_ai_core.schemas import Citation, QueryRequest, RetrievalChunk

router = APIRouter(tags=["retrieval"])


@router.post("/retrieve")
async def retrieve(payload: QueryRequest) -> dict:
    contexts = [
        RetrievalChunk(
            chunk_id="chunk-legal-001",
            score=0.94,
            content=(
                "Nguoi su dung lao dong co nghia vu cap phuong tien bao ve ca nhan "
                "phu hop voi moi truong lam viec."
            ),
            source=Citation(
                document_id="doc-legal-001",
                title="Quy dinh an toan lao dong",
                section="Dieu 12",
                page=5,
                chunk_id="chunk-legal-001",
            ),
        ),
        RetrievalChunk(
            chunk_id="chunk-policy-004",
            score=0.87,
            content=(
                "Chinh sach noi bo quy dinh phong nhan su phai theo doi cap phat PPE "
                "va luu vet cap phat cho tung nhan vien."
            ),
            source=Citation(
                document_id="doc-policy-004",
                title="SOP cap phat PPE",
                section="Muc 3.2",
                page=2,
                chunk_id="chunk-policy-004",
            ),
        ),
    ]

    retrieval_plan = {
        "intent": "policy_lookup",
        "vector_top_k": payload.top_k,
        "graph_expansion": payload.include_graph,
        "re_ranker": "cross-encoder-placeholder",
    }
    return {"plan": retrieval_plan, "contexts": [item.model_dump(mode="json") for item in contexts]}

