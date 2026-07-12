from enterprise_ai_core.embedding import get_embedding_provider


def main() -> None:
    provider = get_embedding_provider()
    provider.embed_queries(["preload embedding model cache"])
    provider.embed_documents(["preload embedding model cache"])
    print(f"Preloaded embedding provider: {provider.__class__.__name__}")


if __name__ == "__main__":
    main()
