from __future__ import annotations

from .extraction import entity_key
from .graphdb import Neo4jClient
from .schemas import ChunkExtractionPayload


def clear_document_graph(*, client: Neo4jClient, document_id: str) -> None:
    with client.driver.session() as session:
        session.run(
            """
            MATCH ()-[r:RELATED_TO {document_id: $document_id}]->()
            DELETE r
            """,
            document_id=document_id,
        ).consume()
        session.run(
            """
            MATCH (:Entity)-[m:MENTIONED_IN]->(:Document {id: $document_id})
            DELETE m
            """,
            document_id=document_id,
        ).consume()


def upsert_extraction_payload(
    *,
    client: Neo4jClient,
    payload: ChunkExtractionPayload,
    document_title: str,
) -> None:
    client.ensure_schema()
    entities_by_id = {entity.id: entity for entity in payload.entities}
    with client.driver.session() as session:
        session.run(
            """
            MERGE (d:Document {id: $document_id})
            SET d.tenant_id = $tenant_id,
                d.title = $document_title,
                d.updated_at = timestamp()
            """,
            document_id=payload.document_id,
            tenant_id=payload.tenant_id,
            document_title=document_title,
        ).consume()

        for entity in payload.entities:
            key = entity_key(entity.canonical_name, entity.entity_type)
            session.run(
                """
                MERGE (e:Entity {tenant_id: $tenant_id, key: $key})
                SET e.name = $name,
                    e.entity_type = $entity_type,
                    e.aliases = $aliases,
                    e.confidence = $confidence,
                    e.attributes = $attributes,
                    e.updated_at = timestamp()
                WITH e
                MATCH (d:Document {id: $document_id})
                MERGE (e)-[m:MENTIONED_IN {chunk_id: $chunk_id, document_id: $document_id}]->(d)
                SET m.confidence = $confidence,
                    m.updated_at = timestamp()
                """,
                tenant_id=payload.tenant_id,
                key=key,
                name=entity.canonical_name,
                entity_type=entity.entity_type,
                aliases=entity.aliases,
                confidence=entity.confidence,
                attributes=entity.attributes,
                document_id=payload.document_id,
                chunk_id=payload.document_chunk_id,
            ).consume()

        for relation in payload.relations:
            source = entities_by_id.get(relation.source_entity_id)
            target = entities_by_id.get(relation.target_entity_id)
            if not source or not target:
                continue
            session.run(
                """
                MERGE (s:Entity {tenant_id: $tenant_id, key: $source_key})
                MERGE (t:Entity {tenant_id: $tenant_id, key: $target_key})
                MERGE (s)-[r:RELATED_TO {
                    tenant_id: $tenant_id,
                    document_id: $document_id,
                    chunk_id: $chunk_id,
                    relation_type: $relation_type,
                    source_key: $source_key,
                    target_key: $target_key
                }]->(t)
                SET r.confidence = $confidence,
                    r.evidence = $evidence,
                    r.updated_at = timestamp()
                """,
                tenant_id=payload.tenant_id,
                document_id=payload.document_id,
                chunk_id=payload.document_chunk_id,
                relation_type=relation.relation_type,
                source_key=entity_key(source.canonical_name, source.entity_type),
                target_key=entity_key(target.canonical_name, target.entity_type),
                confidence=relation.confidence,
                evidence=relation.evidence,
            ).consume()
