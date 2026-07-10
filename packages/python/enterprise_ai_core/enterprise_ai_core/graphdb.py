from __future__ import annotations

from functools import lru_cache
import time

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable

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
        settings = get_settings()
        last_error: Exception | None = None

        for attempt in range(1, settings.neo4j_connect_retries + 1):
            try:
                self.verify_connectivity()
                with self.driver.session() as session:
                    for statement in statements:
                        session.run(statement).consume()
                return
            except (Neo4jError, OSError, ServiceUnavailable) as exc:
                last_error = exc
                if attempt >= settings.neo4j_connect_retries:
                    break
                time.sleep(settings.neo4j_connect_retry_delay_seconds)

        if last_error is None:
            raise RuntimeError("Neo4j schema initialization failed without an explicit exception")
        raise last_error

    def close(self) -> None:
        self.driver.close()


@lru_cache
def get_neo4j_client() -> Neo4jClient:
    return Neo4jClient()
