"""Hard guard filters.

The guard only intercepts pure greetings, pure capability questions,
pure unsafe requests, and pure invalid or punctuation-only inputs. If
the utterance contains any local-life business intent, it should be
passed through as ``safe``.
"""

from __future__ import annotations

import re
from typing import Any

from .normalizer import normalize_text


_GREETING_PATTERNS = (
    r"^(你好|您好|hello|hi|嗨|哈喽|在吗|在不在)$",
    r"^(早上好|下午好|晚上好)$",
)

_CAPABILITY_PATTERNS = (
    r"^(你有什么作用|你能做什么|你可以做什么|你能帮我做什么|你有什么用|你有什么功能|你是谁|你是做什么的|你能干嘛|你能帮我干嘛|你的功能|我能做什么|我可以做什么)$",
)

_UNSAFE_PATTERNS = (
    r"(帮我)?(下单|支付|付款|代付|代买|订座|订餐|订位|预约|代订座|代订餐|直接下单|直接支付)",
    r"(帮我)?(买单|结账|点单|点餐)",
)

_BUSINESS_PATTERNS = (
    r"附近",
    r"推荐",
    r"周边",
    r"商场",
    r"火锅",
    r"餐厅",
    r"饭店",
    r"店铺",
    r"门店",
    r"店",
    r"优惠",
    r"券",
    r"折扣",
    r"营业",
    r"开门",
    r"距离",
    r"几公里",
    r"评分",
    r"人均",
    r"排队",
    r"订座",
    r"咖啡",
    r"奶茶",
    r"烧烤",
    r"烤肉",
    r"海底捞",
    r"麦当劳",
    r"肯德基",
    r"星巴克",
    r"瑞幸",
    r"喜茶",
    r"蜜雪冰城",
    r"霸王茶姬",
    r"茶百道",
)

_PUNCT_ONLY = re.compile(r"^[\s\.,，。！？!?；;:：、~`'\"\-_=+\(\)\[\]{}<>/\\|…·]+$")


def _strip_noise(text: str) -> str:
    return re.sub(r"[\s\.,，。！？!?；;:：、~`'\"\-_=+\(\)\[\]{}<>/\\|…·]+", "", text)


def _matches_any(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def check_hard_guard(text: Any) -> dict:
    """Validate input against hard guard rules.

    Returns a dict with:
      - ``passed``: whether the input should proceed
      - ``label``: one of ``safe`` / ``invalid`` / ``greeting`` / ``capability``
      - ``reason``: short machine-readable reason
      - ``reply``: fixed response if the guard intercepts
    """
    normalised = normalize_text(text)
    stripped = normalised.strip()

    if not stripped or _PUNCT_ONLY.match(stripped):
        return {
            "passed": False,
            "label": "invalid",
            "reason": "empty_or_punctuation_only",
            "reply": "请提供一条有效的文本内容。",
        }

    if _matches_any(_BUSINESS_PATTERNS, stripped):
        return {
            "passed": True,
            "label": "safe",
            "reason": "contains_business_intent",
            "reply": "",
        }

    compact = _strip_noise(stripped)

    if _matches_any(_GREETING_PATTERNS, compact):
        return {
            "passed": False,
            "label": "greeting",
            "reason": "pure_greeting",
            "reply": "你好，我可以帮你查附近门店、优惠和营业状态。",
        }

    if _matches_any(_CAPABILITY_PATTERNS, compact):
        return {
            "passed": False,
            "label": "capability",
            "reason": "pure_capability_question",
            "reply": "我可以帮你查附近门店、优惠、距离和营业状态。",
        }

    if _matches_any(_UNSAFE_PATTERNS, compact):
        return {
            "passed": False,
            "label": "unsafe",
            "reason": "pure_unsafe_request",
            "reply": "出于安全考虑，我不能帮你代下单、代支付或代订座。你可以继续让我帮你查商家、优惠券、营业状态或距离。",
        }

    if len(compact) <= 2:
        return {
            "passed": False,
            "label": "invalid",
            "reason": "too_short_or_noise",
            "reply": "请换一种更明确的说法。",
        }

    return {
        "passed": True,
        "label": "safe",
        "reason": "non_guarded_content",
        "reply": "",
    }
