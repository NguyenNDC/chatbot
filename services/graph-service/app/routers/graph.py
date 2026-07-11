from fastapi import APIRouter, Query

from enterprise_ai_core.graphdb import get_neo4j_client

router = APIRouter(tags=["graph"])
neo4j_client = get_neo4j_client()


@router.get("/entities/{entity_name}/neighbors")
async def entity_neighbors(entity_name: str, tenant_id: str = Query(...)) -> dict:
    query = """
    MATCH (e:Entity)
    WHERE e.tenant_id = $tenant_id AND toLower(e.name) = toLower($entity_name)
    OPTIONAL MATCH (e)-[r:RELATED_TO {tenant_id: $tenant_id}]->(n:Entity {tenant_id: $tenant_id})
    RETURN e.name AS entity_name,
           collect({
               name: n.name,
               relationship: r.relation_type,
               confidence: r.confidence
           }) AS neighbors
    LIMIT 1
    """
    with neo4j_client.driver.session() as session:
        record = session.run(query, entity_name=entity_name, tenant_id=tenant_id).single()
    if not record:
        return {"entity": entity_name, "neighbors": []}
    neighbors = [item for item in record["neighbors"] if item.get("name")]
    return {"entity": record["entity_name"], "neighbors": neighbors}


@router.get("/documents/{document_id}/entities")
async def document_entities(document_id: str, tenant_id: str = Query(...)) -> dict:
    query = """
    MATCH (e:Entity {tenant_id: $tenant_id})-[m:MENTIONED_IN]->(d:Document {id: $document_id, tenant_id: $tenant_id})
    RETURN d.id AS document_id,
           collect({
               name: e.name,
               entity_type: e.entity_type,
               confidence: m.confidence
           }) AS entities
    """
    with neo4j_client.driver.session() as session:
        record = session.run(query, document_id=document_id, tenant_id=tenant_id).single()
    if not record:
        return {"document_id": document_id, "entities": []}
    return {"document_id": record["document_id"], "entities": record["entities"]}
