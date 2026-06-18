import os

file_path = r"d:\javacode\hm-dianping\learning-agent-service\src\learning_agent_service\rag\retrieval_service.py"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

target_code = """        resolved_route_hits = {name: self._resolve_hits(hits) for name, hits in route_hits.items()}
        resolved_fused_hits = self._resolve_hits(fused_hits)
        resolved_reranked_hits = self._resolve_hits(reranked_hits)
        degraded_routes = tuple(name for name, stats in route_stats.items() if stats.get("degraded"))"""

replacement_code = """        # -----------------------------------------------------
        # Relaxed Retry Logic
        # -----------------------------------------------------
        first_hit_count = len(reranked_hits)
        retry_hit_count = 0
        filter_strategy = "no_filter"
        empty_reason = ""
        
        has_strict_filter = any(k in plan.retrieval_filters.extra for k in ("shop_id", "shop_name", "canonical_shop_name", "matched_alias"))

        if first_hit_count == 0 and has_strict_filter:
            # Drop strict filters
            new_extra = dict(plan.retrieval_filters.extra)
            names = []
            for k in ["shop_name", "canonical_shop_name", "matched_alias"]:
                if new_extra.get(k) and new_extra.get(k) not in names:
                    names.append(str(new_extra.get(k)))
            for k in ["shop_id", "shop_name", "canonical_shop_name", "matched_alias", "entity_confidence"]:
                new_extra.pop(k, None)
                
            combined_names = " ".join(names)
            new_semantic = f"{combined_names} {plan.semantic_query}".strip() if combined_names else plan.semantic_query
            new_keyword = f"{combined_names} {plan.keyword_query}".strip() if combined_names else plan.keyword_query
            
            # 兼容旧代码，如果没有 RetrievalFilters 导入则通过 dict 方式
            try:
                from .models import RetrievalFilters
                new_rf = RetrievalFilters(**plan.retrieval_filters.as_dict(), extra=new_extra)
            except Exception:
                new_rf = plan.retrieval_filters # fallback
                new_rf.extra = new_extra

            new_plan = replace(
                plan,
                retrieval_filters=new_rf,
                semantic_query=new_semantic,
                keyword_query=new_keyword,
            )
            filter_strategy = "relaxed_retry"
            
            # Retry Retrieval
            retry_route_hits, retry_route_stats = self._collect_route_hits(new_plan)
            rrf_started_at = time.perf_counter()
            retry_fused_hits = self._limit_fused_hits(
                self._fusion.fuse(
                    retry_route_hits,
                    query_intent=query_intent or None,
                    query_slots=query_slots,
                )
            )
            rrf_latency_ms += (time.perf_counter() - rrf_started_at) * 1000.0
            rerank_started_at = time.perf_counter()
            retry_reranked_hits = self._rerank(new_plan, retry_fused_hits)
            rerank_latency_ms += (time.perf_counter() - rerank_started_at) * 1000.0
            
            # Post filter (prevent cross-shop contamination)
            expected_shop_id = plan.retrieval_filters.extra.get("shop_id")
            filtered_reranked_hits = []
            for hit in retry_reranked_hits:
                hit_shop_id = hit.metadata.get("shop_id") or hit.metadata.get("tenant_id")
                # If we were strictly looking for a branch but hit a different one, skip
                if expected_shop_id and hit_shop_id and str(hit_shop_id) != str(expected_shop_id):
                    continue
                filtered_reranked_hits.append(hit)
                
            reranked_hits = tuple(filtered_reranked_hits)
            route_hits = retry_route_hits
            route_stats = retry_route_stats
            fused_hits = tuple(retry_fused_hits)
            
            retry_hit_count = len(reranked_hits)
            if retry_hit_count == 0:
                empty_reason = "relaxed_retry_still_empty"
        elif first_hit_count > 0:
            if "shop_id" in plan.retrieval_filters.extra:
                filter_strategy = "shop_id"
            elif "canonical_shop_name" in plan.retrieval_filters.extra:
                filter_strategy = "canonical_name"
            elif "matched_alias" in plan.retrieval_filters.extra:
                filter_strategy = "alias"
            elif "shop_name" in plan.retrieval_filters.extra:
                filter_strategy = "raw_shop_name"
        else:
            empty_reason = "no_hits_no_strict_filter"

        resolved_route_hits = {name: self._resolve_hits(hits) for name, hits in route_hits.items()}
        resolved_fused_hits = self._resolve_hits(fused_hits)
        resolved_reranked_hits = self._resolve_hits(reranked_hits)
        degraded_routes = tuple(name for name, stats in route_stats.items() if stats.get("degraded"))"""

if target_code in content:
    content = content.replace(target_code, replacement_code)
    
    metrics_target = """            "empty_route_count": sum(1 for stats in route_stats.values() if stats.get("state") == "empty"),
            "hyde_enabled": self._hyde_enabled,"""
    metrics_replace = """            "empty_route_count": sum(1 for stats in route_stats.values() if stats.get("state") == "empty"),
            "first_hit_count": first_hit_count,
            "retry_hit_count": retry_hit_count,
            "filter_strategy": filter_strategy,
            "raw_shop_name": str(plan.retrieval_filters.extra.get("shop_name", "")),
            "empty_reason": empty_reason,
            "hyde_enabled": self._hyde_enabled,"""
    
    if metrics_target in content:
        content = content.replace(metrics_target, metrics_replace)
    else:
        print("Warning: Metrics target not found")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Successfully modified retrieval_service.py")
else:
    print("Target code not found in retrieval_service.py")
