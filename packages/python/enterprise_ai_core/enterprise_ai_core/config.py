from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = Field(default="service", alias="SERVICE_NAME")
    service_port: int = Field(default=8000, alias="SERVICE_PORT")
    api_prefix: str = "/api/v1"
    app_public_url: str = Field(default="http://localhost:3000", alias="APP_PUBLIC_URL")

    document_service_url: str = Field(
        default="http://localhost:8001", alias="DOCUMENT_SERVICE_URL"
    )
    retrieval_service_url: str = Field(
        default="http://localhost:8002", alias="RETRIEVAL_SERVICE_URL"
    )
    graph_service_url: str = Field(default="http://localhost:8003", alias="GRAPH_SERVICE_URL")
    llm_service_url: str = Field(default="http://localhost:8004", alias="LLM_SERVICE_URL")
    worker_service_url: str = Field(default="http://localhost:8005", alias="WORKER_SERVICE_URL")

    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    openrouter_model_primary: str = Field(
        default="anthropic/claude-3.7-sonnet", alias="OPENROUTER_MODEL_PRIMARY"
    )
    openrouter_model_fallback: str = Field(
        default="openai/gpt-4.1-mini", alias="OPENROUTER_MODEL_FALLBACK"
    )

    postgres_dsn: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/chatbot_graph",
        alias="POSTGRES_DSN",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    rabbitmq_url: str = Field(default="amqp://guest:guest@localhost:5672//", alias="RABBITMQ_URL")
    neo4j_uri: str = Field(default="bolt://localhost:7687", alias="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", alias="NEO4J_USER")
    neo4j_password: str = Field(default="graphpassword", alias="NEO4J_PASSWORD")

    rustfs_endpoint: str = Field(default="http://localhost:9000", alias="RUSTFS_ENDPOINT")
    rustfs_access_key: str = Field(default="admin", alias="RUSTFS_ACCESS_KEY")
    rustfs_secret_key: str = Field(default="adminadmin", alias="RUSTFS_SECRET_KEY")
    rustfs_bucket_raw: str = Field(default="documents-raw", alias="RUSTFS_BUCKET_RAW")
    rustfs_bucket_artifacts: str = Field(
        default="documents-artifacts", alias="RUSTFS_BUCKET_ARTIFACTS"
    )
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")


@lru_cache
def get_settings() -> ServiceSettings:
    return ServiceSettings()
