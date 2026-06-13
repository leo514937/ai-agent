"""Externalized domain rules configuration.

This module loads local-life domain rules from a YAML/JSON config file
or falls back to built-in defaults. The core heuristics logic only
reads from this config, never hardcodes domain tokens directly.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

_CONFIG_PATH_CANDIDATES = (
    "config/domain_rules.json",
    "config/domain_rules.yaml",
    "domain_rules.json",
    "domain_rules.yaml",
)


@dataclass(frozen=True)
class DomainRuleEntry:
    name: str
    tokens: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    slot_hints: dict[str, Any] = field(default_factory=dict)
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class DomainRulesConfig:
    domains: tuple[DomainRuleEntry, ...] = ()
    page_hints: tuple[str, ...] = ()
    context_keys: tuple[str, ...] = ()
    tool_actions: tuple[str, ...] = ()
    rag_actions: tuple[str, ...] = ()
    mixed_actions: tuple[str, ...] = ()
    profile_patterns: tuple[str, ...] = ()
    conversation_recap_patterns: tuple[str, ...] = ()
    approve_tokens: tuple[str, ...] = ()
    reject_tokens: tuple[str, ...] = ()
    greeting_tokens: tuple[str, ...] = ()
    thanks_tokens: tuple[str, ...] = ()
    compare_tokens: tuple[str, ...] = ()
    nearby_tokens: tuple[str, ...] = ()
    detail_tokens: tuple[str, ...] = ()
    route_tokens: tuple[str, ...] = ()
    coupon_tokens: tuple[str, ...] = ()
    booking_tokens: tuple[str, ...] = ()
    navigation_tokens: tuple[str, ...] = ()
    order_tokens: tuple[str, ...] = ()
    status_tokens: tuple[str, ...] = ()
    scene_patterns: dict[str, tuple[str, ...]] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


_BUILTIN_DOMAIN_RULES = DomainRulesConfig(
    domains=(
        DomainRuleEntry(
            name="餐饮",
            tokens=("餐厅", "吃饭", "饭店", "火锅", "烧烤", "咖啡", "奶茶"),
            aliases=("restaurant", "dining", "food"),
            slot_hints={"domain": "local_life", "category": "food"},
            examples=("推荐附近的餐厅", "哪家火锅好吃"),
        ),
        DomainRuleEntry(
            name="美发/美容",
            tokens=("美发", "理发", "美容", "美甲", "造型"),
            aliases=("hairdresser", "beauty", "salon"),
            slot_hints={"domain": "local_life", "category": "beauty"},
            examples=("附近有什么美发店", "推荐一家美容院"),
        ),
        DomainRuleEntry(
            name="按摩/足疗",
            tokens=("按摩", "足疗", "推拿", "SPA", "spa"),
            aliases=("massage", "spa", "foot_care"),
            slot_hints={"domain": "local_life", "category": "wellness"},
            examples=("附近按摩店推荐", "哪家足疗好"),
        ),
    ),
    page_hints=(
        "assistant", "ai", "home", "shop", "shops",
        "blog", "detail", "meituan_search_box",
    ),
    context_keys=(
        "shopId", "shopName", "blogId", "blogTitle",
        "typeId", "typeName", "location", "city", "entry",
    ),
    tool_actions=(
        "booking", "business_status", "cancel_order", "coupon",
        "create_order", "order_status", "package_status", "refund_order",
    ),
    rag_actions=("compare", "detail", "recommend"),
    mixed_actions=("navigation", "coupon_and_detail"),
    profile_patterns=(
        "你有什么功能", "有什么功能", "你有什么工能", "有什么工能",
        "能做什么", "可以做什么", "你会什么", "你有什么能力",
        "你的功能", "介绍一下你", "你是谁", "你是什么",
        "怎么使用你", "怎么用你",
    ),
    conversation_recap_patterns=(
        "你记得我们说过什么吗", "刚才说到哪了", "上一个问题是什么",
        "我们刚才说什么", "继续刚才的话题", "前面我们聊到哪了",
        "回顾一下我们刚才聊了什么",
    ),
    approve_tokens=("确认", "继续执行", "同意", "可以执行", "确认继续", "继续吧"),
    reject_tokens=("先不执行", "拒绝", "取消执行", "不用执行", "先别", "不执行"),
    greeting_tokens=("你好", "您好", "哈喽", "在吗", "hi", "hello", "hey"),
    thanks_tokens=("谢谢", "多谢", "感谢", "thx", "thanks"),
    compare_tokens=("对比", "比较", "区别", "差别", "vs", "比一下"),
    nearby_tokens=(
        "附近推荐", "推荐附近", "附近有", "附近的",
        "周边推荐", "附近好吃", "附近好评", "附近店",
    ),
    detail_tokens=(
        "详情", "详细", "这家店", "这个店", "商家",
        "店铺", "评分", "人均", "营业时间", "口碑", "优惠券",
    ),
    route_tokens=(
        "路线", "怎么去", "导航", "规划", "行程",
        "计划", "路线规划", "安排", "路程",
    ),
    coupon_tokens=("优惠券", "团购", "券", "折扣", "voucher", "coupon", "discount"),
    booking_tokens=("预订", "预约", "订位", "订桌", "booking", "reserve", "book"),
    navigation_tokens=("导航", "路线", "距离", "怎么去", "navigation", "route", "distance"),
    order_tokens=("下单", "支付", "订单", "退款", "order", "pay", "refund"),
    status_tokens=(
        "营业", "开门", "开业", "歇业", "关门", "营业时间",
        "还能用", "可用", "有效", "过期", "使用", "能用",
    ),
    scene_patterns={
        "elder_friendly": ("爸妈", "父母", "长辈", "老人"),
        "quiet": ("别太吵", "安静", "清静"),
        "parking": ("停车", "车位"),
    },
)


def load_domain_rules_config(
    config_path: str | Path | None = None,
    *,
    overrides: dict[str, Any] | None = None,
) -> DomainRulesConfig:
    raw: dict[str, Any] = {}
    candidates = [config_path] if config_path else []
    candidates.extend(_CONFIG_PATH_CANDIDATES)

    for candidate in candidates:
        if candidate is None:
            continue
        path = Path(candidate)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
            if path.suffix in (".yaml", ".yml"):
                try:
                    import yaml
                    raw = yaml.safe_load(text) or {}
                except ImportError:
                    _LOGGER.warning("yaml module not available, falling back to json")
                    raw = json.loads(text)
            else:
                raw = json.loads(text)
            _LOGGER.info("domain_rules_loaded path=%s keys=%s", path, list(raw.keys()))
            break
        except Exception:
            _LOGGER.exception("domain_rules_load_failed path=%s", path)

    if overrides:
        raw.update(overrides)

    if not raw:
        return _BUILTIN_DOMAIN_RULES

    return _build_config_from_raw(raw)


def _build_config_from_raw(raw: dict[str, Any]) -> DomainRulesConfig:
    domains_raw = raw.get("domains", [])
    domains: list[DomainRuleEntry] = []
    for item in domains_raw:
        if isinstance(item, dict):
            domains.append(DomainRuleEntry(
                name=str(item.get("name", "")),
                tokens=tuple(item.get("tokens", ())),
                aliases=tuple(item.get("aliases", ())),
                slot_hints=dict(item.get("slot_hints", {})),
                examples=tuple(item.get("examples", ())),
            ))

    return DomainRulesConfig(
        domains=tuple(domains) if domains else _BUILTIN_DOMAIN_RULES.domains,
        page_hints=tuple(raw.get("page_hints", _BUILTIN_DOMAIN_RULES.page_hints)),
        context_keys=tuple(raw.get("context_keys", _BUILTIN_DOMAIN_RULES.context_keys)),
        tool_actions=tuple(raw.get("tool_actions", _BUILTIN_DOMAIN_RULES.tool_actions)),
        rag_actions=tuple(raw.get("rag_actions", _BUILTIN_DOMAIN_RULES.rag_actions)),
        mixed_actions=tuple(raw.get("mixed_actions", _BUILTIN_DOMAIN_RULES.mixed_actions)),
        profile_patterns=tuple(raw.get("profile_patterns", _BUILTIN_DOMAIN_RULES.profile_patterns)),
        conversation_recap_patterns=tuple(raw.get("conversation_recap_patterns", _BUILTIN_DOMAIN_RULES.conversation_recap_patterns)),
        approve_tokens=tuple(raw.get("approve_tokens", _BUILTIN_DOMAIN_RULES.approve_tokens)),
        reject_tokens=tuple(raw.get("reject_tokens", _BUILTIN_DOMAIN_RULES.reject_tokens)),
        greeting_tokens=tuple(raw.get("greeting_tokens", _BUILTIN_DOMAIN_RULES.greeting_tokens)),
        thanks_tokens=tuple(raw.get("thanks_tokens", _BUILTIN_DOMAIN_RULES.thanks_tokens)),
        compare_tokens=tuple(raw.get("compare_tokens", _BUILTIN_DOMAIN_RULES.compare_tokens)),
        nearby_tokens=tuple(raw.get("nearby_tokens", _BUILTIN_DOMAIN_RULES.nearby_tokens)),
        detail_tokens=tuple(raw.get("detail_tokens", _BUILTIN_DOMAIN_RULES.detail_tokens)),
        route_tokens=tuple(raw.get("route_tokens", _BUILTIN_DOMAIN_RULES.route_tokens)),
        coupon_tokens=tuple(raw.get("coupon_tokens", _BUILTIN_DOMAIN_RULES.coupon_tokens)),
        booking_tokens=tuple(raw.get("booking_tokens", _BUILTIN_DOMAIN_RULES.booking_tokens)),
        navigation_tokens=tuple(raw.get("navigation_tokens", _BUILTIN_DOMAIN_RULES.navigation_tokens)),
        order_tokens=tuple(raw.get("order_tokens", _BUILTIN_DOMAIN_RULES.order_tokens)),
        status_tokens=tuple(raw.get("status_tokens", _BUILTIN_DOMAIN_RULES.status_tokens)),
        scene_patterns=dict(raw.get("scene_patterns", _BUILTIN_DOMAIN_RULES.scene_patterns)),
        raw=raw,
    )


def get_all_domain_tokens(config: DomainRulesConfig | None = None) -> tuple[str, ...]:
    cfg = config or _BUILTIN_DOMAIN_RULES
    tokens: list[str] = []
    for domain in cfg.domains:
        tokens.extend(domain.tokens)
        tokens.extend(domain.aliases)
    return tuple(dict.fromkeys(tokens))


def get_domain_slot_hints(config: DomainRulesConfig | None = None) -> dict[str, dict[str, Any]]:
    cfg = config or _BUILTIN_DOMAIN_RULES
    hints: dict[str, dict[str, Any]] = {}
    for domain in cfg.domains:
        for token in domain.tokens:
            hints[token] = domain.slot_hints
        for alias in domain.aliases:
            hints[alias] = domain.slot_hints
    return hints


__all__ = [
    "DomainRuleEntry",
    "DomainRulesConfig",
    "load_domain_rules_config",
    "get_all_domain_tokens",
    "get_domain_slot_hints",
    "_BUILTIN_DOMAIN_RULES",
]
