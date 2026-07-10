from enterprise_ai_core.embedding import get_embedding_provider


def main() -> None:
    provider = get_embedding_provider()
    provider.embed(["preload BGE-M3 cache"])
    print(f"Preloaded embedding provider: {provider.__class__.__name__}")


if __name__ == "__main__":
    main()
