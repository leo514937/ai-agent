"""Backward-compatible alias for the local-life Qdrant seeding helpers."""

from .seed_parent_child import (  # noqa: F401
    JavaBusinessClient,
    OpenAIEmbeddingAdapter,
    _build_blog_note_chunks,
    _dedupe_chunks,
    _format_seed_summary_lines,
    build_arg_parser,
    build_openai_runtime,
    build_qdrant_runtime,
    get_settings,
    seed_local_life_knowledge,
)


def main(argv=None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    settings = get_settings()
    business_client = JavaBusinessClient(settings=settings)
    openai_runtime = build_openai_runtime(settings.openai)
    qdrant_runtime = build_qdrant_runtime(settings.qdrant)
    embedding_adapter = OpenAIEmbeddingAdapter(runtime=openai_runtime, model=settings.openai.embedding_model)
    try:
        result = seed_local_life_knowledge(
            business_client=business_client,
            qdrant_client=qdrant_runtime.client,
            embedding_adapter=embedding_adapter,
            collection_name=args.collection_name,
            vector_name=args.vector_name,
            vector_size=args.vector_size,
            shop_limit_per_type=args.shop_limit_per_type,
            voucher_limit=args.voucher_limit,
            blog_limit=args.blog_limit,
            batch_size=args.batch_size,
            cleanup_stale_points=args.cleanup_stale_points,
            shop_ids=args.shop_ids or None,
            voucher_ids=args.voucher_ids or None,
            shop_type_ids=args.shop_type_ids or None,
        )
        for line in _format_seed_summary_lines(result):
            print(line)
    finally:
        business_client.close()
    return 0
