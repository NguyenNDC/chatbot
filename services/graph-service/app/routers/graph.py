from fastapi import APIRouter

router = APIRouter(tags=["graph"])


@router.get("/entities/{entity_name}/neighbors")
async def entity_neighbors(entity_name: str) -> dict:
    return {
        "entity": entity_name,
        "neighbors": [
            {"name": "PPE", "relationship": "REQUIRES"},
            {"name": "Nguoi lao dong", "relationship": "PROTECTS"},
            {"name": "Quy dinh an toan lao dong", "relationship": "DERIVED_FROM"},
        ],
    }

