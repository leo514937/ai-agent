"""Fallback hint extraction for the local-life domain."""

from __future__ import annotations

import re

from ..domain.enums import Facet, TaskType
from ..input.normalizer import normalize_text
from .alias_index import iter_alias_tokens

_COUPON_HINTS = (
    "\u6709\u5238",
    "\u4f18\u60e0\u5238",
    "\u4ee3\u91d1\u5238",
    "\u6298\u6263\u5238",
    "\u4f18\u60e0",
    "\u9886\u5238",
    "\u53ef\u7528\u5238",
    "\u56e2\u8d2d",
)
_OPEN_HINTS = (
    "\u8425\u4e1a",
    "\u5f00\u95e8",
    "\u5173\u95e8",
    "\u6253\u70ca",
    "\u505c\u4e1a",
    "\u73b0\u5728\u8425\u4e1a",
    "\u8fd8\u8425\u4e1a",
)
_DISTANCE_HINTS = (
    "\u8ddd\u79bb",
    "\u591a\u8fdc",
    "\u8fd1\u4e0d\u8fd1",
    "\u8fdc\u4e0d\u8fdc",
    "\u51e0\u516c\u91cc",
    "\u8def\u7a0b",
    "\u79bb\u8fd9",
    "\u79bb\u6211",
    "\u9644\u8fd1",
    "\u591a\u4e45\u80fd\u5230",
    "\u591a\u4e45\u5230",
)
_UNSUPPORTED_SERVICE_HINTS = (
    "\u5bc4\u5b58",
    "\u5ba0\u7269",
    "\u505c\u8f66",
    "\u5305\u95f4",
    "\u5305\u53a2",
    "\u505c\u8f66\u4f4d",
    "\u5145\u7535",
    "\u65e0\u969c\u788d",
    "\u513f\u7ae5\u6905",
    "\u513f\u7ae5\u5ea7\u6905",
    "\u513f\u7ae5\u9910\u6905",
    "\u540c\u6b65\u96f6\u552e",
    "\u54a8\u8be2\u670d\u52a1",
    "\u670d\u52a1\u9879",
    "\u914d\u5957\u670d\u52a1",
    "\u65e0\u969c\u788d\u901a\u9053",
    "\u65e0\u969c\u788d\u8bbe\u65bd",
)
_OPTIONAL_HINTS = (
    "\u987a\u4fbf",
    "\u6700\u597d",
    "\u4e5f\u770b",
    "\u4e00\u8d77\u770b",
    "\u518d\u770b",
    "\u9644\u5e26",
)
_RECOMMENDATION_HINTS = (
    "\u63a8\u8350",
    "\u9644\u8fd1",
    "\u5468\u8fb9",
    "\u627e\u51e0\u5bb6",
    "\u60f3\u627e",
    "\u6709\u6ca1\u6709\u9002\u5408",
)
_CATEGORY_HINTS = (
    "\u706b\u9505",
    "\u9910\u5385",
    "\u996d\u9986",
    "\u5496\u5561",
    "\u5976\u8336",
    "\u8336\u996e",
    "\u70e7\u70e4",
    "\u70e7\u8089",
    "\u5feb\u9910",
    "\u4e2d\u9910",
    "\u897f\u9910",
    "\u65e5\u6599",
    "\u751c\u54c1",
)
_SCENE_HINTS = (
    "\u7ea6\u4f1a",
    "\u670b\u53cb\u805a\u9910",
    "\u805a\u9910",
    "\u5bb6\u5ead\u805a\u9910",
    "\u5546\u52a1",
    "\u8bf7\u5ba2",
    "\u591c\u5bb5",
)
_CANCEL_HINTS = (
    "算了",
    "不用了",
    "不查了",
    "别查了",
    "取消",
    "先不看了",
    "放弃",
    "不选了",
)
_NEW_TASK_HINTS = (
    "不要",
    "换成",
    "改成",
    "推荐咖啡",
    "推荐茶",
    "重新推荐",
    "重新找",
)
_COMPARISON_HINTS = (
    "\u5bf9\u6bd4",
    "\u6bd4\u4e00\u6bd4",
    "\u6bd4\u5462",
    "\u54ea\u4e2a\u66f4",
    "\u54ea\u5bb6\u66f4",
    "\u8c01\u66f4",
    "\u66f4\u597d",
    "\u66f4\u4f18",
    "\u54ea\u4e2a\u597d",
    "\u54ea\u5bb6\u597d",
    "\u8fd9\u4e09\u5bb6",
    "\u8fd9\u51e0\u5bb6",
)
_ORDINAL_ALIASES = {
    "\u7b2c\u4e00\u5bb6": "\u7b2c\u4e00\u5bb6",
    "\u7b2c\u4e8c\u5bb6": "\u7b2c\u4e8c\u5bb6",
    "\u7b2c\u4e09\u5bb6": "\u7b2c\u4e09\u5bb6",
    "\u7b2c\u4e00\u4e2a": "\u7b2c\u4e00\u5bb6",
    "\u7b2c\u4e8c\u4e2a": "\u7b2c\u4e8c\u5bb6",
    "\u7b2c\u4e09\u4e2a": "\u7b2c\u4e09\u5bb6",
    "\u7b2c\u4e00\u95f4": "\u7b2c\u4e00\u5bb6",
    "\u7b2c\u4e8c\u95f4": "\u7b2c\u4e8c\u5bb6",
    "\u7b2c\u4e09\u95f4": "\u7b2c\u4e09\u5bb6",
}
_DEICTIC_HINTS = (
    "这家",
    "那家",
    "这间",
    "那间",
    "这三家",
    "这几家",
    "这些",
    "上面这些",
    "刚才这几家",
    "这几个",
    "这几间",
    "这三个",
)
_NOISE_RE = re.compile(r"[\s,\.\?!;:()\[\]{}<>/\\|\"'\u3001\uff0c\u3002\uff01\uff1f\uff1b\uff1a]+")
_EXPLORATION_SPLIT_RE = re.compile(r"(?:(先|然后|再|之后|接着|最后|再去|再找)+)")
_LOCATION_REFERENCE_RE = re.compile(r"([^\s，。！？]{2,20}?附近)")
_TIME_HINTS = {
    "evening": ("晚上", "夜晚", "晚间", "傍晚"),
    "half_day": ("半日", "半天", "半日游", "半日路线"),
    "morning": ("早上", "上午", "清晨"),
    "noon": ("中午",),
    "night": ("夜里", "深夜"),
}
_SCENE_HINT_MAP = {
    "date": ("约会", "恋爱", "情侣"),
    "parent_child": ("亲子", "带娃", "孩子", "儿童"),
    "friends_party": ("聚餐", "朋友聚会", "朋友聚餐"),
}
_EXPLORATION_CUE_HINTS = ("安排", "路线", "行程", "怎么安排", "游", "半日游", "约会", "先", "再", "然后", "之后", "接着", "最后")
_STAGE_EVIDENCE_MAP = {
    "eat": ["detail", "open_status", "distance"],
    "eat_hotpot": ["detail", "open_status", "distance", "coupon"],
    "coffee": ["detail", "open_status", "distance"],
    "drink": ["detail", "open_status", "distance"],
    "dessert": ["detail", "open_status", "distance"],
    "walk": ["scene_fit", "distance"],
    "parent_child_activity": ["scene_fit", "detail", "distance"],
    "shopping": ["detail", "distance", "open_status"],
    "entertainment": ["detail", "distance", "open_status"],
    "rest": ["detail", "distance", "open_status"],
}


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _shop_tokens() -> list[tuple[str, str]]:
    tokens = list(iter_alias_tokens())
    tokens.sort(key=lambda item: len(item[0]), reverse=True)
    return tokens


def _extract_merchant_mentions(text: str) -> list[str]:
    normalized = normalize_text(text)
    mentions: list[str] = []
    for token, canonical in _shop_tokens():
        if token and token in normalized:
            mentions.append(token)
    return _dedupe(mentions)


def _extract_ordinals(text: str) -> list[str]:
    hits = [canonical for token, canonical in _ORDINAL_ALIASES.items() if token in text]
    digits = []
    if "1" in text:
        digits.append("\u7b2c\u4e00\u5bb6")
    if "2" in text:
        digits.append("\u7b2c\u4e8c\u5bb6")
    if "3" in text:
        digits.append("\u7b2c\u4e09\u5bb6")
    return _dedupe(hits + digits)


_GROUP_DEICTIC_RE = re.compile(
    r"(这|前)\s*([1-9]\d*|[一二两三四五六七八九十]+)\s*(家|个|间)"
)


def _extract_deictic(text: str) -> list[str]:
    hits = [hint for hint in _DEICTIC_HINTS if hint in text]
    for match in _GROUP_DEICTIC_RE.finditer(text):
        hits.append(match.group(0))
    return _dedupe(hits)


def _facet_positions(text: str) -> list[tuple[int, str]]:
    positions: list[tuple[int, str]] = []
    for facet_name, hints in (
        (Facet.coupon.value, _COUPON_HINTS),
        (Facet.open_status.value, _OPEN_HINTS),
        (Facet.distance.value, _DISTANCE_HINTS),
    ):
        indexes = [text.find(hint) for hint in hints if hint in text]
        if indexes:
            positions.append((min(indexes), facet_name))
    positions.sort(key=lambda item: item[0])
    return positions


def _build_facets(text: str) -> list[dict[str, object]]:
    ordered = _facet_positions(text)
    optional_mode = any(hint in text for hint in _OPTIONAL_HINTS)
    facets: list[dict[str, object]] = []
    for index, (_pos, facet_name) in enumerate(ordered):
        required = not optional_mode or index == 0
        facets.append({"name": facet_name, "required": required})
    return facets


def _extract_hints(text: str, hints: tuple[str, ...]) -> list[str]:
    return _dedupe([hint for hint in hints if hint in text])


def _unsupported_facets(text: str) -> tuple[list[str], list[str]]:
    normalized = normalize_text(text)
    service_cues = ("有没有", "是否", "能不能", "能否", "可不可以", "提供", "支持", "服务", "设施")
    matched = [hint for hint in _UNSUPPORTED_SERVICE_HINTS if hint and hint in normalized]
    if not matched or not any(cue in normalized for cue in service_cues):
        return [], []
    return ["service_feature"], _dedupe([f"unsupported_service:{hint}" for hint in matched])


def _surface_hints(text: str) -> list[str]:
    hints: list[str] = []
    hints.extend(_extract_hints(text, _COUPON_HINTS))
    hints.extend(_extract_hints(text, _OPEN_HINTS))
    hints.extend(_extract_hints(text, _DISTANCE_HINTS))
    hints.extend(_extract_hints(text, _OPTIONAL_HINTS))
    hints.extend(_extract_hints(text, _RECOMMENDATION_HINTS))
    hints.extend(_extract_hints(text, _CATEGORY_HINTS))
    hints.extend(_extract_hints(text, _SCENE_HINTS))
    hints.extend(_extract_hints(text, _COMPARISON_HINTS))
    return _dedupe(hints)


def _extract_scene(text: str) -> str:
    for scene, hints in _SCENE_HINT_MAP.items():
        if any(hint in text for hint in hints):
            return scene
    return ""


def _extract_time(text: str) -> str:
    for time_label, hints in _TIME_HINTS.items():
        if any(hint in text for hint in hints):
            return time_label
    return ""


def _alias_hints(text: str) -> list[str]:
    normalized = normalize_text(text)
    hits: list[str] = []
    for token, canonical in _shop_tokens():
        if token and token in normalized:
            hits.append(token)
    return _dedupe(hits)


def _comparison_focus(text: str) -> str:
    for facet_name, hints in (
        ("coupon", _COUPON_HINTS),
        ("open_status", _OPEN_HINTS),
        ("distance", _DISTANCE_HINTS),
        ("rating", ("\u8bc4\u5206", "\u53e3\u7891", "\u8bc4\u4ef7")),
        ("value_for_money", ("\u6027\u4ef7\u6bd4", "\u5212\u7b97", "\u503c\u4e0d\u503c", "\u9ad8\u6027\u4ef7\u6bd4")),
        ("overall", ("\u54ea\u4e2a\u66f4\u597d", "\u54ea\u5bb6\u66f4\u597d", "\u8c01\u66f4\u597d")),
    ):
        if any(hint in text for hint in hints):
            return facet_name
    return ""


def _comparison_focused_facets(text: str) -> list[str]:
    facets: list[str] = []
    for facet_name, hints in (
        ("coupon", _COUPON_HINTS),
        ("open_status", _OPEN_HINTS),
        ("distance", _DISTANCE_HINTS),
        ("rating", ("\u8bc4\u5206", "\u53e3\u7891", "\u8bc4\u4ef7")),
        ("value_for_money", ("\u6027\u4ef7\u6bd4", "\u5212\u7b97", "\u503c\u4e0d\u503c", "\u9ad8\u6027\u4ef7\u6bd4")),
    ):
        if any(hint in text for hint in hints):
            facets.append(facet_name)
    if not facets and any(hint in text for hint in ("\u66f4\u597d", "\u66f4\u4f18", "\u54ea\u4e2a\u597d", "\u54ea\u5bb6\u597d")):
        facets.append("overall")
    return _dedupe(facets)


def _looks_like_comparison(
    text: str,
    mentions: list[str],
    ordinal_references: list[str],
    deictic_references: list[str],
) -> bool:
    if any(hint in text for hint in _COMPARISON_HINTS):
        return True
    if "\u548c" in text and "\u6bd4" in text and (mentions or ordinal_references or deictic_references):
        return True
    if "\u6bd4" in text and len(mentions) + len(ordinal_references) + len(deictic_references) >= 2:
        return True
    return False


def _looks_like_recommendation(text: str, query_terms: list[str], scene_terms: list[str]) -> bool:
    if any(hint in text for hint in _RECOMMENDATION_HINTS):
        return True
    return bool(query_terms and ("\u9644\u8fd1" in text or "\u63a8\u8350" in text or scene_terms))


def _recommendation_query_terms(text: str) -> list[str]:
    return _extract_hints(text, _CATEGORY_HINTS)


def _recommendation_scene_terms(text: str) -> list[str]:
    return _extract_hints(text, _SCENE_HINTS)


def _detect_cancel_intent(text: str) -> bool:
    return any(hint in text for hint in _CANCEL_HINTS)


def _detect_new_task_override(text: str) -> bool:
    return any(hint in text for hint in _NEW_TASK_HINTS) and any(token in text for token in ("推荐", "查", "找", "看看"))


def _detect_discourse_marker(text: str) -> str:
    for marker in ("先", "然后", "再", "之后", "接着", "最后"):
        if marker in text:
            return marker
    return ""


def _split_exploration_fragments(text: str) -> list[str]:
    fragments = [segment.strip() for segment in re.split(r"(?:先|然后|再|之后|接着|最后|再去|再找|并且|同时|以及|、|；|;|,|，)", text) if segment and segment.strip()]
    cleaned: list[str] = []
    for fragment in fragments:
        fragment = fragment.strip()
        if fragment and fragment not in cleaned:
            cleaned.append(fragment)
    return cleaned


def _is_generic_exploration_fragment(fragment: str) -> bool:
    compact = str(fragment or "").strip()
    if not compact:
        return True
    generic_markers = (
        "帮我安排",
        "安排一下",
        "帮我",
        "怎么安排",
        "路线",
        "行程",
        "探索安排",
        "约会路线",
    )
    return compact in generic_markers or compact in {"安排", "路线", "行程"}


def _stage_type_for_fragment(fragment: str) -> tuple[str, str]:
    if any(token in fragment for token in ("火锅",)):
        return "eat_hotpot", "hotpot"
    if any(token in fragment for token in ("吃饭", "餐", "饭", "晚餐", "午餐", "午饭", "早饭")):
        return "eat", "eat"
    if any(token in fragment for token in ("咖啡", "茶", "奶茶")):
        return "coffee", "coffee"
    if any(token in fragment for token in ("甜品", "甜点", "蛋糕", "dessert")):
        return "dessert", "dessert"
    if any(token in fragment for token in ("散步", "走走", "逛逛", "walk")):
        return "walk", "walk"
    if any(token in fragment for token in ("亲子", "带娃", "儿童", "孩子")):
        return "parent_child_activity", "parent_child"
    if any(token in fragment for token in ("购物", "商场", "逛街", "shopping")):
        return "shopping", "shopping"
    if any(token in fragment for token in ("电影", "看展", "展览", "游玩", "游乐", "娱乐", "玩")):
        return "entertainment", "entertainment"
    if any(token in fragment for token in ("休息", "坐坐", "歇会", "休闲")):
        return "rest", "rest"
    return "custom", fragment[:20] or "custom"


def _stage_evidence_requirements(stage_type: str) -> list[str]:
    return list(_STAGE_EVIDENCE_MAP.get(stage_type, ["detail"]))


def _build_stage_entry(
    *,
    index: int,
    fragment: str,
    stage_type: str,
    category: str,
    scene: str,
    time_label: str,
    location_reference: dict[str, object] | None,
) -> dict[str, object]:
    location = dict(location_reference or {})
    if stage_type == "eat_hotpot":
        candidate_query = "火锅"
    elif stage_type == "eat":
        candidate_query = "餐厅"
    elif stage_type == "coffee":
        candidate_query = "咖啡店"
    elif stage_type == "dessert":
        candidate_query = "甜品店"
    elif stage_type == "walk":
        candidate_query = "散步 公园"
    elif stage_type == "parent_child_activity":
        candidate_query = "亲子活动 儿童乐园"
    elif stage_type == "shopping":
        candidate_query = "商场 购物"
    elif stage_type == "entertainment":
        candidate_query = "娱乐 电影 体验"
    elif stage_type == "rest":
        candidate_query = "休息 坐坐"
    else:
        candidate_query = fragment or category or scene or "探索安排"
    return {
        "stage_id": f"stage_{index}",
        "stage_type": stage_type,
        "category": category or stage_type,
        "location": location,
        "time": time_label,
        "scene": scene,
        "constraints": {
            "time": time_label,
            "scene": scene,
            "location_required": not bool(location),
        },
        "order": index,
        "required": True,
        "candidate_query": candidate_query,
        "evidence_requirements": _stage_evidence_requirements(stage_type),
        "fallback_strategy": "search_then_select" if location else "ask_clarification_again",
        "status": "planned",
        "query": candidate_query,
        "notes": fragment,
    }


def _build_exploration_stages(text: str, scene_terms: list[str], *, scene: str = "", time_label: str = "", location_reference: dict[str, object] | None = None, category: str = "") -> list[dict[str, object]]:
    has_cue = any(hint in text for hint in _EXPLORATION_CUE_HINTS)
    fragments = _split_exploration_fragments(text)
    stages: list[dict[str, object]] = []

    if len(fragments) >= 2:
        stage_index = 0
        for fragment in fragments[:3]:
            stage_type, inferred_category = _stage_type_for_fragment(fragment)
            if stage_type == "custom" and _is_generic_exploration_fragment(fragment):
                continue
            stage_index += 1
            stages.append(
                _build_stage_entry(
                    index=stage_index,
                    fragment=fragment,
                    stage_type=stage_type,
                    category=inferred_category or category,
                    scene=scene,
                    time_label=time_label,
                    location_reference=location_reference,
                )
            )
        return stages

    if not has_cue and not scene and not time_label and not scene_terms and len(fragments) < 2:
        return []

    default_stage_types: list[str]
    if any(token in text for token in ("火锅",)) and any(token in text for token in ("咖啡", "茶", "奶茶")):
        default_stage_types = ["eat_hotpot", "coffee"]
    elif scene == "date" or any(token in text for token in ("约会",)):
        default_stage_types = ["eat", "coffee", "walk"]
    elif scene == "parent_child":
        default_stage_types = ["eat", "parent_child_activity", "rest"]
    elif time_label == "half_day":
        default_stage_types = ["eat", "entertainment", "rest"]
    else:
        default_stage_types = ["eat", "coffee"]

    for index, stage_type in enumerate(default_stage_types[:3], start=1):
        candidate_fragment = scene_terms[0] if scene_terms else category or text
        stages.append(
            _build_stage_entry(
                index=index,
                fragment=candidate_fragment,
                stage_type=stage_type,
                category=category or stage_type,
                scene=scene,
                time_label=time_label,
                location_reference=location_reference,
            )
        )
    return stages


def _build_location_reference(text: str) -> dict[str, object] | None:
    match = _LOCATION_REFERENCE_RE.search(text)
    if not match:
        return None
    ref_text = match.group(1)
    return {"reference_type": "location_reference", "text": ref_text, "location_name": ref_text, "resolved": False}


def _has_coupon_preference(text: str) -> bool:
    return any(hint in text for hint in _COUPON_HINTS)


def _has_open_preference(text: str) -> bool:
    return any(hint in text for hint in _OPEN_HINTS)


def _has_nearby_preference(text: str) -> bool:
    return any(hint in text for hint in ("\u9644\u8fd1", "\u5468\u8fb9", "\u8fd1\u4e00\u70b9", "\u522b\u592a\u8fdc", "\u79bb\u6211\u8fd1"))


def _build_comparison_targets(
    mentions: list[str],
    ordinal_references: list[str],
    deictic_references: list[str],
) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    for mention in mentions:
        targets.append({"shop_name": mention, "reference": "explicit", "source_text": mention})
    for token in ordinal_references:
        targets.append({"shop_name": token, "reference": "ordinal", "source_text": token})
    for token in deictic_references:
        targets.append({"shop_name": token, "reference": "deictic", "source_text": token})
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in targets:
        key = f"{item.get('reference', '')}|{item.get('shop_name', '')}|{item.get('source_text', '')}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def extract_slots(text: str, top_intent: str) -> dict:
    normalized = normalize_text(text)
    simplified = _NOISE_RE.sub(" ", normalized)
    mentions = _alias_hints(normalized)
    ordinal_references = _extract_ordinals(normalized)
    deictic_references = _extract_deictic(normalized)
    facets = _build_facets(simplified)
    surface_hints = _surface_hints(simplified)
    alias_hints = mentions
    unsupported_facets, unsupported_reasons = _unsupported_facets(simplified)
    query_terms = _recommendation_query_terms(simplified)
    scene_terms = _recommendation_scene_terms(simplified)
    scene = _extract_scene(simplified)
    time_label = _extract_time(simplified)
    cancel_intent = _detect_cancel_intent(simplified)
    new_task_override = _detect_new_task_override(simplified)
    discourse_marker = _detect_discourse_marker(simplified)
    location_reference = _build_location_reference(simplified)
    exploration_stages = _build_exploration_stages(
        simplified,
        scene_terms,
        scene=scene,
        time_label=time_label,
        location_reference=location_reference,
        category=query_terms[0] if query_terms else "",
    )
    comparison = _looks_like_comparison(simplified, mentions, ordinal_references, deictic_references)
    recommendation = _looks_like_recommendation(simplified, query_terms, scene_terms) and not comparison

    task_type: TaskType | None = None
    primary_task = ""
    workflow_hint = ""
    need_context = False
    reference_mentions: list[str] = []
    comparison_targets: list[dict[str, str]] = []
    focused_facets: list[str] = []
    comparison_focus = ""
    comparison_facets: list[str] = []
    preferences: list[dict[str, object]] = []

    if top_intent == "local_life":
        if cancel_intent:
            task_type = TaskType.clarification_reply
            primary_task = "clarification_reply"
            workflow_hint = "clarification_reply"
        elif new_task_override:
            task_type = TaskType.recommendation
            primary_task = "recommendation"
            workflow_hint = "recommendation"
        if comparison:
            task_type = TaskType.comparison
            primary_task = "comparison"
            workflow_hint = "comparison"
            reference_mentions = _dedupe(ordinal_references + deictic_references)
            comparison_targets = _build_comparison_targets(mentions, ordinal_references, deictic_references)
            focused_facets = _comparison_focused_facets(simplified)
            comparison_focus = _comparison_focus(simplified)
            comparison_facets = list(focused_facets)
            need_context = not bool(mentions or ordinal_references or deictic_references)
        elif recommendation:
            task_type = TaskType.recommendation
            primary_task = "recommendation"
            workflow_hint = "recommendation"
        elif facets:
            task_type = (
                TaskType.coupon_query
                if len(facets) == 1 and facets[0]["name"] == Facet.coupon.value
                else TaskType.single_shop_query
            )
            primary_task = "coupon_query" if task_type == TaskType.coupon_query else "single_shop_query"
            workflow_hint = task_type.value
            focused_facets = [str(facet.get("name", "") or "").strip() for facet in facets if str(facet.get("name", "") or "").strip()]
            need_context = not bool(mentions or ordinal_references or deictic_references)
        elif mentions:
            task_type = TaskType.single_shop_query
            primary_task = "single_shop_query"
            workflow_hint = "single_shop_query"

    soft_preferences: dict[str, object] = {}
    ranking_signals: dict[str, object] = {}
    if recommendation:
        if scene_terms:
            soft_preferences["scene_terms"] = scene_terms
            ranking_signals["scene_terms"] = scene_terms
        if scene:
            soft_preferences["scene"] = scene
            ranking_signals["scene"] = scene
        if time_label:
            soft_preferences["time"] = time_label
            ranking_signals["time"] = time_label
        if query_terms:
            ranking_signals["query_terms"] = query_terms
            ranking_signals["category"] = query_terms[0]
        if _has_open_preference(simplified):
            soft_preferences["open_now_preferred"] = True
            ranking_signals["open_now_preferred"] = True
        if _has_coupon_preference(simplified):
            soft_preferences["coupon_preferred"] = True
            ranking_signals["coupon_preferred"] = True
        if _has_nearby_preference(simplified):
            soft_preferences["nearby_preferred"] = True
            ranking_signals["nearby_preferred"] = True
        if any(token in simplified for token in ("性价比", "划算", "值不值", "值不值", "高性价比")):
            soft_preferences["price_preference"] = "value_for_money"
            soft_preferences["ranking_policy"] = "value_for_money_first"
            ranking_signals["value_for_money_preferred"] = True
            ranking_signals["ranking_policy"] = "value_for_money_first"
            preferences.append({"type": "value_for_money", "text": "性价比高"})
        if any(token in simplified for token in ("比较便宜", "便宜一点", "更便宜", "更便宜点", "便宜些")):
            soft_preferences["price_preference"] = "lower_price"
            ranking_signals["price_preference"] = "lower_price"
            preferences.append({"type": "price", "operator": "lower", "text": "比较便宜"})

    if comparison and not preferences:
        if comparison_focus:
            preferences.append({"type": "comparison_focus", "text": comparison_focus})
        if comparison_facets:
            preferences.append({"type": "comparison_facets", "values": comparison_facets})

    confidence = 0.9 if task_type is not None else 0.6
    if mentions or ordinal_references or deictic_references:
        confidence = max(confidence, 0.85)
    if cancel_intent or new_task_override or exploration_stages:
        confidence = min(confidence, 0.7)

    preference_signals = [
        {"preference_type": "value_for_money", "value": "value_for_money", "text": "性价比高"} if any(token in simplified for token in ("性价比", "划算", "值不值", "高性价比")) else None,
        {"preference_type": "relative_price_preference", "value": "relative_price_preference", "text": "比较便宜"} if any(token in simplified for token in ("比较便宜", "便宜一点", "更便宜", "更便宜点", "便宜些")) else None,
        {"preference_type": "scene_preference", "value": scene_terms[0], "text": scene_terms[0]} if scene_terms else None,
    ]
    preference_signals = [item for item in preference_signals if item is not None]

    filter_signals = [
        {"filter_type": "coupon_filter", "value": True, "required": True, "text": "有券"} if _has_coupon_preference(simplified) else None,
        {"filter_type": "open_now_filter", "value": True, "required": True, "text": "现在营业"} if _has_open_preference(simplified) else None,
        {"filter_type": "distance_filter", "value": True, "required": True, "text": "附近"} if _has_nearby_preference(simplified) else None,
    ]
    filter_signals = [item for item in filter_signals if item is not None]

    if comparison and len(comparison_targets) >= 2:
        comparison_structure = "multi_target"
    elif comparison and ordinal_references:
        comparison_structure = "ordinal"
    elif comparison and deictic_references:
        comparison_structure = "deictic"
    elif comparison and mentions:
        comparison_structure = "explicit"
    else:
        comparison_structure = "unknown"

    if exploration_stages and not comparison and not cancel_intent:
        workflow_hint = "exploration_planning"
        primary_task = "exploration"
        if task_type is None:
            task_type = TaskType.recommendation

    return {
        "top_intent": top_intent,
        "intent": top_intent,
        # DEPRECATED_COMPAT: 迁移期兼容输出，最终语义权威仍由 semantic_parse 提供。
        "task_type": task_type,
        "primary_task": primary_task,
        # DEPRECATED_COMPAT: 仅用于兼容 workflow 迁移，不作为最终调度权威。
        "workflow_hint": workflow_hint,
        "comparison_intent": comparison,
        "comparison_structure": comparison_structure,
        "comparison_facets": comparison_facets,
        "exploration_stages": exploration_stages,
        "scene": scene,
        "time": time_label,
        "missing_slots": ["comparison_targets"] if comparison and not comparison_targets else (["missing_exploration_location"] if exploration_stages and not location_reference else []),
        "preferences": preferences,
        "preference_signals": preference_signals,
        "location": {"text": location_reference["text"], "location_name": location_reference["location_name"]} if location_reference else {},
        "category": query_terms[0] if query_terms else "",
        "shop_target": {"shop_name": mentions[0], "text": mentions[0]} if mentions and not comparison else None,
        "reference": {"comparison_targets": comparison_targets, "location_reference": location_reference} if comparison_targets or location_reference else {},
        "location_reference": location_reference,
        "shop_reference": {"reference_type": "shop_reference", "text": mentions[0], "shop_name": mentions[0], "resolved": False} if mentions and not comparison else None,
        "ordinal_reference": {"reference_type": "ordinal_reference", "text": ordinal_references[0], "value": ordinal_references, "resolved": False} if ordinal_references else None,
        "deictic_reference": {"reference_type": "deictic_reference", "text": deictic_references[0], "value": deictic_references, "resolved": False} if deictic_references else None,
        "filters": {},
        "filter_signals": filter_signals,
        "facets": facets,
        "merchant_mentions": mentions,
        "brand_mentions": [],
        "branch_mentions": [],
        "reference_mentions": reference_mentions,
        "comparison_targets": comparison_targets,
        "ordinal_references": ordinal_references,
        "deictic_references": deictic_references,
        "focused_facets": focused_facets,
        "unsupported_facets": unsupported_facets,
        "unsupported_reasons": unsupported_reasons,
        "comparison_focus": comparison_focus,
        "hard_constraints": {},
        "soft_preferences": soft_preferences,
        "ranking_signals": ranking_signals,
        "surface_hints": surface_hints,
        "alias_hints": alias_hints,
        "follow_up": {"is_follow_up": True, "refine_action": "restart"} if new_task_override else ({"is_follow_up": True, "refine_action": "other"} if cancel_intent else None),
        "confidence": confidence,
        "need_context": need_context or bool(location_reference and not mentions) or (bool(exploration_stages) and not location_reference),
        "discourse_marker": discourse_marker,
        "constraint_update": bool(new_task_override or ("一点" in simplified or "更" in simplified or "少点" in simplified)),
        "new_task_override": new_task_override,
        "cancel_intent": cancel_intent,
        "missing_slot_type": "missing_exploration_location" if exploration_stages and not location_reference else "",
    }
