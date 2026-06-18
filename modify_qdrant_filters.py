import os

file_path = r"d:\javacode\hm-dianping\learning-agent-service\src\learning_agent_service\rag\qdrant_filters.py"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

target_code = """    def _build_clauses(self, context: QdrantFilterContext) -> list[FieldCondition]:
        clauses: list[FieldCondition] = []
        filters = context.retrieval_filters

        for key, values in filters.as_dict().items():
            if not values:
                continue
            clauses.append(self._build_field_condition(key, values))

        if context.tenant_id:
            clauses.append(FieldCondition(key="tenant_id", match=MatchValue(value=context.tenant_id)))
        if context.permission_tags:
            clauses.append(FieldCondition(key="permission_tags", match=MatchAny(any=list(context.permission_tags))))
        if context.is_active is not None:
            clauses.append(FieldCondition(key="is_active", match=MatchValue(value=bool(context.is_active))))

        for key, value in context.runtime_context.items():
            if key in _RUNTIME_FILTER_KEYS:
                continue
            if value is None or value == "":
                continue
            clauses.append(self._build_field_condition(key, self._normalize_values(value)))

        return clauses"""

replacement_code = """    def _build_clauses(self, context: QdrantFilterContext) -> list[FieldCondition]:
        clauses: list[FieldCondition] = []
        filters = context.retrieval_filters
        
        # 提取 shop 相关的特定 key 进行优先处理
        runtime = context.runtime_context
        shop_id = self._normalize_single(runtime.get("shop_id"))
        canonical_shop_name = self._normalize_single(runtime.get("canonical_shop_name"))
        matched_alias = self._normalize_single(runtime.get("matched_alias"))
        confidence_str = self._normalize_single(runtime.get("entity_confidence"))
        confidence = float(confidence_str) if confidence_str else 0.0
        raw_shop_name = self._normalize_single(runtime.get("shop_name"))

        shop_filtered = False
        if shop_id and confidence >= 0.8:
            clauses.append(FieldCondition(key="shop_id", match=MatchValue(value=int(shop_id) if shop_id.isdigit() else shop_id)))
            shop_filtered = True
        elif canonical_shop_name and confidence >= 0.8:
            clauses.append(FieldCondition(key="shop_name", match=MatchValue(value=canonical_shop_name)))
            shop_filtered = True
        elif matched_alias and confidence >= 0.6:
            clauses.append(FieldCondition(key="alias_names", match=MatchAny(any=[matched_alias])))
            shop_filtered = True
        elif raw_shop_name and confidence < 0.5:
            # 置信度低，不加 shop_name 强过滤，完全依赖向量相似度
            shop_filtered = True
            
        handled_keys = {"shop_id", "canonical_shop_name", "matched_alias", "entity_confidence", "candidate_shop_ids"}
        if shop_filtered:
            handled_keys.add("shop_name")

        for key, values in filters.as_dict().items():
            if not values or key in handled_keys:
                continue
            clauses.append(self._build_field_condition(key, values))

        if context.tenant_id:
            clauses.append(FieldCondition(key="tenant_id", match=MatchValue(value=context.tenant_id)))
        if context.permission_tags:
            clauses.append(FieldCondition(key="permission_tags", match=MatchAny(any=list(context.permission_tags))))
        if context.is_active is not None:
            clauses.append(FieldCondition(key="is_active", match=MatchValue(value=bool(context.is_active))))

        for key, value in context.runtime_context.items():
            if key in _RUNTIME_FILTER_KEYS or key in handled_keys:
                continue
            if value is None or value == "":
                continue
            clauses.append(self._build_field_condition(key, self._normalize_values(value)))

        return clauses"""

if target_code in content:
    content = content.replace(target_code, replacement_code)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Successfully modified qdrant_filters.py")
else:
    print("Target code not found in qdrant_filters.py")
