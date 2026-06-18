from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from learning_agent_service.domain.utils import as_mapping as _as_mapping

from .schemas import LocalLifeSlots
from learning_agent_service.local_life.catalog import LocalLifeCatalog, get_default_catalog
from learning_agent_service.local_life.candidate_generator import CandidateGenerator
from learning_agent_service.local_life.semantic_selector import SemanticSelector
from learning_agent_service.local_life.target_shop_policy import TargetShop, TargetShopPolicy


def _explicit_entity_from_query(query: str) -> str | None:
    if not query:
        return None
        
    compact = query.strip()
    match = re.match(r"^(?P<name>.+?)(?:\s+)?(?:怎么样|好不好|值不值得|适合约会|有券吗|现在营业吗|现在还营业吗|营业吗|在哪里|在哪|有优惠吗)[？?]*$", compact)
    if match:
        prefix = match.group("name").strip(" 的,，。！？!?")
        if prefix:
            return _strip_facet_suffixes(prefix)

    from learning_agent_service.local_life.target_shop_policy import _PRONOUNS
    for pronoun in _PRONOUNS:
        if pronoun in compact and len(compact) <= len(pronoun) + 5: # simple check
            return pronoun

    from .catalog import get_default_catalog
    catalog = get_default_catalog()
    query_lower = query.lower()
    
    # Match longest shop name first
    shops = sorted(catalog.shops, key=lambda s: len(s.name or ""), reverse=True)
    for shop in shops:
        name = shop.name or ""
        if not name:
            continue
        if name.lower() in query_lower:
            return name
        
        # Simple alias generation for matching (e.g. "海底捞火锅" -> "海底捞")
        short_name = name.split("(")[0].split("（")[0].replace("火锅", "").replace("餐厅", "").replace("菜馆", "").strip()
        if short_name and len(short_name) > 1 and short_name.lower() in query_lower:
            return short_name
            
    return None

def _strip_facet_suffixes(text: str) -> str:
    # 把门店名后面拼进来的查询尾巴和业态尾巴递归剥离掉，避免把“有券吗/营业吗”当成店名一部分。
    suffixes = [
        "有券吗",
        "现在营业吗",
        "现在还营业吗",
        "营业吗",
        "怎么样",
        "好不好",
        "值不值得",
        "适合约会",
        "有优惠吗",
        "在哪里",
        "在哪",
        "店",
        "餐厅",
        "火锅",
    ]
    cleaned = str(text or "").strip()
    while cleaned:
        next_text = cleaned
        for suffix in suffixes:
            if next_text.endswith(suffix):
                next_text = next_text[: -len(suffix)].strip(" 的,，。！？!?")
                break
        if next_text == cleaned:
            return cleaned
        cleaned = next_text
    return cleaned

def _first_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _get_val(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)


class EntityResolver:
    def __init__(
        self,
        catalog: LocalLifeCatalog | None = None,
        candidate_generator: CandidateGenerator | None = None,
        semantic_selector: SemanticSelector | None = None,
        target_policy: TargetShopPolicy | None = None,
        runtime: Any | None = None,
    ):
        if runtime is None:
            try:
                from learning_agent_service.local_life.hybrid_router import get_hybrid_router
                router = get_hybrid_router()
                if router:
                    runtime = router.runtime
            except Exception:
                pass
        self.catalog = catalog or get_default_catalog()
        self.candidate_generator = candidate_generator or CandidateGenerator()
        self.semantic_selector = semantic_selector or SemanticSelector(runtime=runtime)
        self.validator = target_policy or TargetShopPolicy()

    def resolve(
        self,
        *,
        raw_query: str,
        slots: Any,
        user_need: Any | None = None,
        session_context: Mapping[str, Any] | None = None,
        query_route: Any | None = None,
        client_context: Mapping[str, Any] | None = None,
        explicit_entity: str | None = None,
    ) -> TargetShop:
        """Backwards-compatible alias for resolve_target."""
        return self.resolve_target(
            raw_query=raw_query,
            slots=slots,
            user_need=user_need,
            session_context=session_context,
            query_route=query_route,
            client_context=client_context,
            explicit_entity=explicit_entity,
        )

    def resolve_target(
        self,
        *,
        raw_query: str,
        slots: Any,
        user_need: Any | None = None,
        session_context: Mapping[str, Any] | None = None,
        query_route: Any | None = None,
        client_context: Mapping[str, Any] | None = None,
        explicit_entity: str | None = None,
    ) -> TargetShop:
        session_context_map = _as_mapping(session_context)
        client_context_map = _as_mapping(client_context)
        
        if isinstance(slots, Mapping):
            slots_obj = LocalLifeSlots(**slots)
        else:
            slots_obj = slots

        # 1. Candidate Generation
        candidates = self.candidate_generator.generate_candidates(
            raw_query=raw_query,
            slots=slots_obj,
            session_context=session_context_map,
            client_context=client_context_map
        )

        # 2. Semantic Selection via LLM
        selection = self.semantic_selector.select(
            query=raw_query,
            candidates=candidates,
            session_context=session_context_map
        )

        # 3. Policy Validation
        return self.validator.validate(
            raw_query=raw_query,
            candidates=candidates,
            selection=selection,
            session_context=session_context_map,
            client_context=client_context_map,
        )
