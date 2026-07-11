from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = Field(default="service", alias="SERVICE_NAME")
    service_port: int = Field(default=8000, alias="SERVICE_PORT")
    api_prefix: str = "/api/v1"
    app_public_url: str = Field(default="http://localhost:3000", alias="APP_PUBLIC_URL")
    cors_allow_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        alias="CORS_ALLOW_ORIGINS",
    )

    document_service_url: str = Field(
        default="http://localhost:8001", alias="DOCUMENT_SERVICE_URL"
    )
    retrieval_service_url: str = Field(
        default="http://localhost:8002", alias="RETRIEVAL_SERVICE_URL"
    )
    graph_service_url: str = Field(default="http://localhost:8003", alias="GRAPH_SERVICE_URL")
    llm_service_url: str = Field(default="http://localhost:8004", alias="LLM_SERVICE_URL")
    worker_service_url: str = Field(default="http://localhost:8005", alias="WORKER_SERVICE_URL")
    gateway_service_timeout_seconds: int = Field(
        default=20, alias="GATEWAY_SERVICE_TIMEOUT_SECONDS"
    )
    gateway_query_retrieval_timeout_seconds: int = Field(
        default=30, alias="GATEWAY_QUERY_RETRIEVAL_TIMEOUT_SECONDS"
    )
    gateway_query_llm_timeout_seconds: int = Field(
        default=180, alias="GATEWAY_QUERY_LLM_TIMEOUT_SECONDS"
    )

    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    openrouter_model_primary: str = Field(
        default="openai/gpt-oss-20b", alias="OPENROUTER_MODEL_PRIMARY"
    )
    openrouter_model_fallback: str = Field(
        default="openai/gpt-4.1-mini", alias="OPENROUTER_MODEL_FALLBACK"
    )
    openrouter_model_extraction: str = Field(
        default="openai/gpt-oss-20b", alias="OPENROUTER_MODEL_EXTRACTION"
    )

    postgres_dsn: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/chatbot_graph",
        alias="POSTGRES_DSN",
    )
    postgres_connect_retries: int = Field(default=20, alias="POSTGRES_CONNECT_RETRIES")
    postgres_connect_retry_delay_seconds: int = Field(
        default=3, alias="POSTGRES_CONNECT_RETRY_DELAY_SECONDS"
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    rabbitmq_url: str = Field(default="amqp://guest:guest@localhost:5672//", alias="RABBITMQ_URL")
    neo4j_uri: str = Field(default="bolt://localhost:7687", alias="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", alias="NEO4J_USER")
    neo4j_password: str = Field(default="graphpassword", alias="NEO4J_PASSWORD")
    neo4j_connect_retries: int = Field(default=20, alias="NEO4J_CONNECT_RETRIES")
    neo4j_connect_retry_delay_seconds: int = Field(
        default=3, alias="NEO4J_CONNECT_RETRY_DELAY_SECONDS"
    )

    rustfs_endpoint: str = Field(default="http://localhost:9000", alias="RUSTFS_ENDPOINT")
    rustfs_access_key: str = Field(default="admin", alias="RUSTFS_ACCESS_KEY")
    rustfs_secret_key: str = Field(default="adminadmin", alias="RUSTFS_SECRET_KEY")
    rustfs_bucket_raw: str = Field(default="documents-raw", alias="RUSTFS_BUCKET_RAW")
    rustfs_bucket_artifacts: str = Field(
        default="documents-artifacts", alias="RUSTFS_BUCKET_ARTIFACTS"
    )
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")
    document_max_upload_bytes: int = Field(default=50_000_000, alias="DOCUMENT_MAX_UPLOAD_BYTES")
    chunk_target_tokens: int = Field(default=320, alias="CHUNK_TARGET_TOKENS")
    chunk_overlap_tokens: int = Field(default=48, alias="CHUNK_OVERLAP_TOKENS")
    embedding_provider: str = Field(default="bge-m3", alias="EMBEDDING_PROVIDER")
    embedding_model_name: str = Field(default="BAAI/bge-m3", alias="EMBEDDING_MODEL_NAME")
    embedding_dimension: int = Field(default=1024, alias="EMBEDDING_DIMENSION")
    ocr_engine: str = Field(default="tesseract", alias="OCR_ENGINE")
    ocr_languages: str = Field(default="vie+eng", alias="OCR_LANGUAGES")
    ocr_min_characters: int = Field(default=40, alias="OCR_MIN_CHARACTERS")
    ocr_render_dpi: int = Field(default=220, alias="OCR_RENDER_DPI")
    tesseract_cmd: str = Field(default="", alias="TESSERACT_CMD")
    hf_home: str = Field(default="/opt/hf-cache", alias="HF_HOME")
    worker_task_max_retries: int = Field(default=2, alias="WORKER_TASK_MAX_RETRIES")
    worker_task_retry_delay_seconds: int = Field(
        default=15, alias="WORKER_TASK_RETRY_DELAY_SECONDS"
    )
    worker_dead_letter_queue: str = Field(
        default="document.dead_letter", alias="WORKER_DEAD_LETTER_QUEUE"
    )
    graph_extract_max_concurrency: int = Field(
        default=6, alias="GRAPH_EXTRACT_MAX_CONCURRENCY"
    )
    graph_extract_progress_log_interval: int = Field(
        default=10, alias="GRAPH_EXTRACT_PROGRESS_LOG_INTERVAL"
    )
    graph_extract_commit_interval: int = Field(
        default=5, alias="GRAPH_EXTRACT_COMMIT_INTERVAL"
    )
    retrieval_graph_hops: int = Field(default=2, alias="RETRIEVAL_GRAPH_HOPS")
    retrieval_graph_candidate_limit: int = Field(
        default=12, alias="RETRIEVAL_GRAPH_CANDIDATE_LIMIT"
    )
    retrieval_min_final_score: float = Field(
        default=0.22, alias="RETRIEVAL_MIN_FINAL_SCORE"
    )
    retrieval_compare_extra_k: int = Field(default=4, alias="RETRIEVAL_COMPARE_EXTRA_K")
    llm_context_max_chunks: int = Field(default=6, alias="LLM_CONTEXT_MAX_CHUNKS")
    llm_context_char_budget: int = Field(default=8000, alias="LLM_CONTEXT_CHAR_BUDGET")
    llm_answer_max_tokens: int = Field(default=900, alias="LLM_ANSWER_MAX_TOKENS")
    openrouter_timeout_seconds: int = Field(default=90, alias="OPENROUTER_TIMEOUT_SECONDS")
    openrouter_max_retries: int = Field(default=2, alias="OPENROUTER_MAX_RETRIES")


@lru_cache
def get_settings() -> ServiceSettings:
    return ServiceSettings()
