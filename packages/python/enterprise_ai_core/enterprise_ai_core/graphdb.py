from __future__ import annotations

from functools import lru_cache

from neo4j import GraphDatabase

from .config import get_settings


class Neo4jClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    def verify_connectivity(self) -> None:
        self.driver.verify_connectivity()

    def ensure_schema(self) -> None:
        statements = [
            "CREATE CONSTRAINT entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE (e.tenant_id, e.key) IS UNIQUE",
            "CREATE CONSTRAINT document_key IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
        ]
        with self.driver.session() as session:
            for statement in statements:
                session.run(statement).consume()

    def close(self) -> None:
        self.driver.close()


@lru_cache
def get_neo4j_client() -> Neo4jClient:
    return Neo4jClient()
