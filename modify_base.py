import os

file_path = r"d:\javacode\hm-dianping\learning-agent-service\src\learning_agent_service\application\routing_signals\base.py"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

target_code = """    shop_id = slots.get("shop_id") or persistent.selected_shop_id
    if shop_id is not None:
        try:
            shop_id_int = int(shop_id)
            retrieval_filters["shop_id"] = shop_id_int
            retrieval_filters["candidate_shop_ids"] = [shop_id_int]
        except (ValueError, TypeError):
            retrieval_filters["shop_id"] = shop_id"""

replacement_code = """    shop_id = slots.get("shop_id") or persistent.selected_shop_id
    if shop_id is not None:
        try:
            shop_id_int = int(shop_id)
            retrieval_filters["shop_id"] = shop_id_int
            retrieval_filters["candidate_shop_ids"] = [shop_id_int]
        except (ValueError, TypeError):
            retrieval_filters["shop_id"] = shop_id

    # 1. Entity Resolver 介入
    try:
        from learning_agent_service.local_life.entity_resolver import EntityResolver
        from types import SimpleNamespace
        resolver_slots = SimpleNamespace(
            shop_ids=[int(shop_id)] if shop_id else [],
            shop_query=shop_name
        )
        resolver = EntityResolver()
        target_shop = resolver.resolve_target(
            raw_query=normalized_query,
            slots=resolver_slots,
            client_context=client_context,
            session_context=persistent.model_dump(),
            explicit_entity=explicit_shop
        )
        
        if target_shop.shop_id is not None:
            retrieval_filters["shop_id"] = target_shop.shop_id
            
        if target_shop.shop_name:
            retrieval_filters["canonical_shop_name"] = target_shop.shop_name
            
        retrieval_filters["entity_confidence"] = target_shop.confidence
        if target_shop.candidate_shop_ids:
            retrieval_filters["candidate_shop_ids"] = target_shop.candidate_shop_ids
            
        # Add original resolved alias for fallback matching
        if target_shop.raw_mention and target_shop.raw_mention != target_shop.shop_name:
            retrieval_filters["matched_alias"] = target_shop.raw_mention
            
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"EntityResolver fallback in synthesize_retrieval_plan: {e}")"""

if target_code in content:
    content = content.replace(target_code, replacement_code)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Successfully modified base.py")
else:
    print("Target code not found in base.py")
