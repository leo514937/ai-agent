"""B2-mini-verifier for LLM Verbalizer output boundary checks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..domain.schemas import DecisionPlan


def _load_all_known_shop_names() -> list[str]:
    mock_file = Path(__file__).resolve().parent.parent / "mock_data" / "shops.json"
    if not mock_file.exists():
        return []
    try:
        with open(mock_file, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
            names = []
            for item in data:
                if item.get("shop_name"):
                    names.append(str(item["shop_name"]).strip())
                if item.get("alias"):
                    names.append(str(item["alias"]).strip())
                for a in item.get("aliases", []) or []:
                    names.append(str(a).strip())
            return list(set(names))
    except Exception:
        return []


def _is_number(s: Any) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


class B2MiniVerifier:
    """Verifier executing 5 minimal checks on verbalizer output."""

    def verify(self, plan: DecisionPlan, response_text: str) -> dict[str, Any]:
        violations: list[str] = []

        # 1. LLM 不得新增 DecisionPlan 外的 shop_name
        known_names = _load_all_known_shop_names()
        allowed_names = set()
        for item in plan.selected_targets + plan.omitted_targets:
            if item.get("shop_name"):
                allowed_names.add(str(item["shop_name"]).strip())
                brand_name = str(item["shop_name"]).strip()
                if "(" in brand_name:
                    allowed_names.add(brand_name.split("(", 1)[0].strip())
            if item.get("alias"):
                allowed_names.add(str(item["alias"]).strip())

        for name in known_names:
            if name in response_text:
                is_allowed = False
                for allowed in allowed_names:
                    if name in allowed or allowed in name:
                        is_allowed = True
                        break
                if not is_allowed:
                    violations.append("hallucinated_shop_name")
                    break

        # 2. unknown 不得被说成“没有” (unknown_as_false)
        coupon_unknown = False
        open_status_unknown = False
        distance_unknown = False

        for note in plan.uncertainty_notes:
            if "优惠" in note or "券" in note:
                coupon_unknown = True
            if "营业" in note or "打烊" in note:
                open_status_unknown = True
            if "距离" in note:
                distance_unknown = True

        for target in plan.selected_targets:
            c_status = target.get("coupon_status")
            if c_status == "unknown":
                coupon_unknown = True
            open_val = target.get("open_status")
            if open_val == "unknown":
                open_status_unknown = True

        # Negative coupon claims
        if coupon_unknown:
            negative_coupon_phrases = ["没有券", "肯定没券", "无券", "没有可用券", "暂无可用券", "没有优惠券"]
            for phrase in negative_coupon_phrases:
                if phrase in response_text:
                    violations.append("unknown_as_false")
                    break

        # Negative open status claims
        if open_status_unknown:
            negative_open_phrases = ["一定关门", "肯定打烊", "已打烊", "不营业", "关门了", "没营业", "没有开门"]
            for phrase in negative_open_phrases:
                if phrase in response_text:
                    violations.append("unknown_as_false")
                    break

        # 3. LLM 不得新增 DecisionPlan 外的距离、价格、评分等信息
        allowed_distances = set()
        allowed_prices = set()
        allowed_ratings = set()

        for target in plan.selected_targets:
            dist = target.get("distance_km")
            if dist is not None:
                allowed_distances.add(str(dist))
                allowed_distances.add(f"{dist:.1f}" if isinstance(dist, (int, float)) else str(dist))
            price = target.get("avg_price")
            if price is not None:
                allowed_prices.add(str(price))
            rating = target.get("rating")
            if rating is not None:
                allowed_ratings.add(str(rating))
                allowed_ratings.add(f"{rating:.1f}" if isinstance(rating, (int, float)) else str(rating))

        for point in plan.factual_points:
            numbers = re.findall(r"\d+(?:\.\d+)?", point)
            for num in numbers:
                if "评分" in point:
                    allowed_ratings.add(num)
                if "距离" in point:
                    allowed_distances.add(num)
                if "价格" in point or "人均" in point:
                    allowed_prices.add(num)

        # Distance check
        response_distances = re.findall(r"(\d+(?:\.\d+)?)\s*(?:公里|km|米)", response_text)
        for dist in response_distances:
            if not allowed_distances or not any(float(dist) == float(allowed) for allowed in allowed_distances if _is_number(allowed)):
                violations.append("unsupported_distance")
                break

        # Price check
        response_prices = re.findall(r"(\d+)\s*元", response_text)
        for price in response_prices:
            if not allowed_prices or not any(int(price) == int(float(allowed)) for allowed in allowed_prices if _is_number(allowed)):
                violations.append("unsupported_price")
                break

        # Rating check
        response_ratings = re.findall(r"(\d+\.\d+)\s*分|评分\s*(\d+\.\d+)", response_text)
        ratings = [r[0] or r[1] for r in response_ratings if r[0] or r[1]]
        for r in ratings:
            if not allowed_ratings or not any(float(r) == float(allowed) for allowed in allowed_ratings if _is_number(allowed)):
                violations.append("unsupported_rating")
                break

        # Coupon check (if no coupons are allowed at all, cannot claim they exist)
        if "券" in response_text or "优惠" in response_text:
            has_allowed_coupon = False
            for target in plan.selected_targets:
                c_status = target.get("coupon_status")
                if c_status in ("has_coupon", "ok"):
                    has_allowed_coupon = True
                cnt = target.get("coupon_count")
                if cnt is not None and cnt > 0:
                    has_allowed_coupon = True
            for point in plan.factual_points:
                if "券" in point or "优惠" in point:
                    has_allowed_coupon = True
            if not has_allowed_coupon:
                is_negative = any(neg in response_text for neg in ["没有券", "暂无", "无券", "无法确认", "没查到", "不知道"])
                if not is_negative:
                    violations.append("unsupported_coupon")

        # 4. LLM 不得改变排序
        expected_shops = []
        for item in plan.overall_ranking:
            name = str(item.get("shop_name", "")).strip()
            if name:
                expected_shops.append(item)

        shop_indices = []
        for idx, shop in enumerate(expected_shops):
            name = str(shop.get("shop_name", "")).strip()
            brand = name.split("(", 1)[0].strip() if "(" in name else name
            alias = str(shop.get("alias", "")).strip()

            pos = -1
            for candidate in (name, brand, alias):
                if candidate:
                    found = response_text.find(candidate)
                    if found >= 0:
                        if pos == -1 or found < pos:
                            pos = found
            if pos >= 0:
                shop_indices.append((pos, idx))

        shop_indices.sort(key=lambda x: x[0])
        ranked_indices = [idx for _, idx in shop_indices]
        if ranked_indices != sorted(ranked_indices):
            violations.append("ranking_changed")

        # 5. forbidden claims / omitted targets 要触发 fallback
        for claim in plan.forbidden_claims:
            if claim in response_text:
                violations.append("forbidden_claim_violation")

        if plan.omitted_targets:
            forbidden_phrases = ["对比了所有", "对比了全部", "分析了全部", "分析了所有", "对比了全部几家", "对比了全部店"]
            for phrase in forbidden_phrases:
                if phrase in response_text:
                    violations.append("omitted_targets_violation")

        passed = len(violations) == 0
        return {
            "passed": passed,
            "violations": violations,
            "violation": violations[0] if violations else None,
        }
