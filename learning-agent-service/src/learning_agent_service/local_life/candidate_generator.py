import re
from typing import Any, Mapping
from learning_agent_service.local_life.schemas import CandidateShop, LocalLifeSlots
from learning_agent_service.local_life.catalog import get_default_catalog

_PRONOUNS = ("这家", "这店", "这间", "它", "他", "她", "刚才那家", "刚才那个", "这商家", "这个商家", "这几家", "第一家", "第二家", "第三家", "上面那家", "刚推荐的")

_EXPLICIT_SUFFIXES = (
    "现在营业吗",
    "现在开门营业吗",
    "开门营业吗",
    "现在有券吗",
    "有团购吗",
    "团购吗",
    "有什么优惠",
    "优惠吗",
    "现在能不能订",
    "现在能不能约",
    "现在开吗",
    "适合带爸妈吗",
    "适合家庭聚餐吗",
    "怎么样呢",
    "有券吗呢",
    "营业吗呢",
    "怎么样",
    "有券吗",
    "有券",
    "有几张券",
    "have_coupon",
    "有代金券吗",
    "有折扣吗",
    "有套餐吗",
    "有可用优惠券吗",
    "适合约会吗",
    "适合吗",
    "好不好",
    "值不值得",
    "值不值",
    "营业吗",
    "呢",
    "店呢",
    "家呢",
    "商家呢",
    "哪个呢",
    "有啥特色",
    "有什么特色",
    "特色是什么",
)

def _strip_facet_suffixes(text: str) -> str:
    prefix = text.strip().rstrip("？?。.!！")
    _question_verb_patterns = (
        "有券吗", "有优惠吗", "有优惠券吗", "有没有券", "有没有优惠",
        "有券", "有优惠", "营业吗", "开门吗", "现在营业吗", "现在开门", "现在开门吗", "开门营业",
    )
    changed = True
    while changed:
        changed = False
        for suffix in sorted(_EXPLICIT_SUFFIXES, key=len, reverse=True):
            if prefix.endswith(suffix):
                prefix = prefix[: -len(suffix)].strip(" ，,;；")
                changed = True
                break
        if not changed:
            for pat in _question_verb_patterns:
                if prefix.endswith(pat):
                    prefix = prefix[: -len(pat)].strip(" ，,;；")
                    changed = True
                    break
    return prefix

def _explicit_entity_from_query(raw_query: str) -> str | None:
    compact = (raw_query or "").strip()
    if not compact:
        return None

    generic_query_tokens = ("附近", "推荐", "餐厅", "餐馆", "美食", "店铺", "店家", "一家", "帮我找", "找个", "我在")
    has_entity_shape = "（" in compact or "(" in compact or "店" in compact

    suffixes = tuple(
        dict.fromkeys(
            [
                "什么",
                "哪家",
                "哪个好",
                "行不行",
                "可以吗",
                "多少钱",
                "怎么走",
                "在哪里",
                "在哪",
                *_EXPLICIT_SUFFIXES,
            ]
        )
    )

    for suffix in suffixes:
        idx = compact.find(suffix)
        if idx > 0 and len(compact) - idx == len(suffix):
            prefix = compact[:idx].strip(" 的,，。！？!?")
            if prefix and prefix not in _PRONOUNS and (
                not any(token in prefix for token in generic_query_tokens)
                or has_entity_shape
            ):
                return _strip_facet_suffixes(prefix)

    for suffix in _EXPLICIT_SUFFIXES:
        if compact.endswith(suffix):
            prefix = compact[: -len(suffix)].strip(" 的,，。！？!?")
            if prefix and not any(pronoun in prefix for pronoun in _PRONOUNS):
                if not any(token in prefix for token in generic_query_tokens) or has_entity_shape:
                    return _strip_facet_suffixes(prefix)

    match = re.match(r"^(?P<name>.+?)(?:\s+)?(?:怎么样|好不好|值不值得|适合约会|有券吗|现在营业吗|现在还营业吗|营业吗|在哪里|在哪|有优惠吗)$", compact)
    if match:
        prefix = match.group("name").strip(" 的,，。！？!?")
        if prefix and not any(pronoun in prefix for pronoun in _PRONOUNS):
            return _strip_facet_suffixes(prefix)
    return None

class CandidateGenerator:
    def __init__(self):
        self.catalog = get_default_catalog()
        
    def generate_candidates(
        self,
        raw_query: str,
        slots: LocalLifeSlots,
        session_context: Mapping[str, Any] | None = None,
        client_context: Mapping[str, Any] | None = None,
    ) -> list[CandidateShop]:
        candidates: dict[int, CandidateShop] = {}
        session_map = dict(session_context or {})
        client_map = dict(client_context or {})
        
        # 1. Fetch from Contexts
        self._add_from_context(session_map, candidates, match_type="session")
        self._add_from_context(client_map, candidates, match_type="client")
        
        # 2. Add Explicit Extractions (Exact/Alias/Fuzzy from Catalog)
        explicit_entity = _explicit_entity_from_query(raw_query)
        lookup_name = explicit_entity or slots.shop_query
        
        if lookup_name and lookup_name.strip() not in _PRONOUNS:
            catalog_matches = self.catalog.search_shops(query=lookup_name, slots=slots, limit=5)
            for item in catalog_matches:
                if item.id in candidates:
                    candidates[item.id].score += 0.5
                    continue
                    
                match_type = "fuzzy"
                if lookup_name.lower() == item.name.lower():
                    match_type = "exact"
                elif lookup_name.lower() in item.name.lower():
                    match_type = "alias"
                    
                candidates[item.id] = CandidateShop(
                    shop_id=item.id,
                    canonical_name=item.name,
                    matched_text=lookup_name,
                    match_type=match_type,
                    score=1.0 if match_type == "exact" else (0.8 if match_type == "alias" else 0.5)
                )

        return sorted(list(candidates.values()), key=lambda x: x.score, reverse=True)

    def _add_from_context(self, context_map: dict[str, Any], candidates: dict[int, CandidateShop], match_type: str):
        # Current Shop
        shop_id = context_map.get("selected_shop_id") or context_map.get("current_shop_id") or context_map.get("shopId") or context_map.get("shop_id")
        shop_name = context_map.get("selected_shop_name") or context_map.get("current_shop") or context_map.get("shopName") or context_map.get("shop_name")
        
        try:
            shop_id_int = int(shop_id) if shop_id else None
            if shop_id_int and shop_id_int not in candidates and shop_name:
                candidates[shop_id_int] = CandidateShop(
                    shop_id=shop_id_int,
                    canonical_name=str(shop_name),
                    matched_text=str(shop_name),
                    match_type=match_type,
                    score=0.95
                )
        except (ValueError, TypeError):
            pass
            
        # Candidates list
        last_candidates = context_map.get("last_candidates") or []
        if isinstance(last_candidates, list):
            for i, cand in enumerate(last_candidates):
                if not isinstance(cand, dict):
                    continue
                c_id = cand.get("shop_id") or cand.get("id")
                c_name = cand.get("shop_name") or cand.get("name")
                try:
                    c_id_int = int(c_id) if c_id else None
                    if c_id_int and c_id_int not in candidates and c_name:
                        candidates[c_id_int] = CandidateShop(
                            shop_id=c_id_int,
                            canonical_name=str(c_name),
                            matched_text=str(c_name),
                            match_type=match_type,
                            score=0.7 - (i * 0.01) # Slight decay for lower ranked candidates
                        )
                except (ValueError, TypeError):
                    pass
