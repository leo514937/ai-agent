"""B2-mini-verifier for LLM Verbalizer output boundary checks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..domain.schemas import DecisionPlan


def _load_all_known_shop_names() -> list[str]:
    # Static mock data removed in P1; returns empty (no name-based verification)
    return []


def _is_number(s: Any) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def _extract_shop_clauses(text: str, shop_names: list[str]) -> dict[str, list[str]]:
    # Split text into clauses by common punctuation and newlines
    clauses = re.split(r'[，。；\n\r、]', text)
    shop_to_clauses = {name: [] for name in shop_names}
    
    current_shop = None
    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue
        found_shops = []
        for name in shop_names:
            if name in clause:
                found_shops.append(name)
        if len(found_shops) == 1:
            current_shop = found_shops[0]
            shop_to_clauses[current_shop].append(clause)
        elif len(found_shops) > 1:
            for name in found_shops:
                shop_to_clauses[name].append(clause)
            current_shop = None
        else:
            if current_shop:
                shop_to_clauses[current_shop].append(clause)
    return shop_to_clauses


class B2MiniVerifier:
    """Verifier executing enhanced boundary checks on verbalizer output."""

    def verify(self, plan: DecisionPlan, response_text: str) -> dict[str, Any]:
        violations: list[str] = []

        # --- 1. 店铺边界校验 & shop_mismatch ---
        known_names = _load_all_known_shop_names()
        allowed_names = set()
        shop_id_to_name = {}
        
        # Add targets and summaries
        for item in plan.selected_targets + plan.omitted_targets:
            if item.get("shop_name"):
                name = str(item["shop_name"]).strip()
                allowed_names.add(name)
                shop_id_to_name[item.get("shop_id", "")] = name
                brand_name = name
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
                    violations.append("shop_mismatch")
                    break

        # --- 2. unknown_as_false & tool_failure_as_fact & empty_result_as_negative ---
        # Map targets to ease checking
        target_by_name = {}
        for target in plan.selected_targets:
            name = target.get("shop_name", "")
            if name:
                target_by_name[name] = target
                brand = name.split("(", 1)[0].strip() if "(" in name else name
                target_by_name[brand] = target

        # Heuristic checks based on extracted clauses per shop
        shop_to_clauses = _extract_shop_clauses(response_text, list(target_by_name.keys()))
        
        for name, clauses in shop_to_clauses.items():
            target = target_by_name.get(name)
            if not target:
                continue
            
            # Coupon status check
            coupon_status = target.get("coupon_status", "unknown")
            unknown_facts = target.get("unknown_facts") or []
            failed_facts = target.get("failed_facts") or []
            
            is_coupon_failed = coupon_status == "failed" or "coupon" in failed_facts
            is_coupon_unknown = (coupon_status == "unknown" or "coupon" in unknown_facts) and not is_coupon_failed
            is_coupon_empty = coupon_status == "empty"
            
            # Open status check
            open_status = target.get("open_status", "unknown")
            is_open_failed = open_status == "failed" or "open_status" in failed_facts
            is_open_unknown = (open_status == "unknown" or "open_status" in unknown_facts) and not is_open_failed
            
            # Distance check
            dist_km = target.get("distance_km")
            is_dist_failed = "distance" in failed_facts
            is_dist_unknown = (dist_km is None or "distance" in unknown_facts) and not is_dist_failed
            
            # Price check
            avg_price = target.get("avg_price")
            is_price_failed = "detail" in failed_facts
            is_price_unknown = (avg_price is None or "detail" in unknown_facts) and not is_price_failed
            
            # Rating check
            rating = target.get("rating")
            is_rating_failed = "detail" in failed_facts
            is_rating_unknown = (rating is None or "detail" in unknown_facts) and not is_rating_failed

            for clause in clauses:
                # Validate Coupon Claims
                if "券" in clause or "优惠" in clause or "折扣" in clause or "省钱" in clause:
                    negative_coupon = any(neg in clause for neg in ["没有券", "肯定没券", "无券", "没有可用券", "暂无可用券", "没有优惠券", "暂无优惠券", "未提供优惠"])
                    positive_coupon = any(pos in clause for pos in ["有券", "优惠券", "可以领券", "可用券"])
                    
                    if is_coupon_unknown:
                        if negative_coupon:
                            violations.extend(["unknown_as_false", "unsupported_coupon"])
                        elif positive_coupon:
                            violations.extend(["tool_failure_as_fact", "unsupported_coupon"])
                    elif is_coupon_failed:
                        violations.extend(["tool_failure_as_fact", "unsupported_coupon"])
                    elif is_coupon_empty:
                        # Cannot claim positive coupon when empty
                        if positive_coupon and not negative_coupon:
                            violations.extend(["empty_result_as_negative", "unsupported_coupon"])
                
                # Validate Open Status Claims
                if "营业" in clause or "开门" in clause or "打烊" in clause or "关门" in clause:
                    open_claims = ["营业中", "正在营业", "正常营业", "开门"]
                    closed_claims = ["打烊", "关门", "不营业", "未营业"]
                    if is_open_unknown:
                        if any(c in clause for c in open_claims + closed_claims):
                            violations.extend(["unknown_as_false", "unsupported_open_status"])
                    elif is_open_failed:
                        if any(c in clause for c in open_claims + closed_claims):
                            violations.extend(["tool_failure_as_fact", "unsupported_open_status"])
                            
                # Validate Distance Claims
                if any(x in clause for x in ["距离", "公里", "km", "米", "很近", "很远", "不远"]):
                    if is_dist_unknown:
                        violations.extend(["unknown_as_false", "unsupported_distance"])
                    elif is_dist_failed:
                        violations.extend(["tool_failure_as_fact", "unsupported_distance"])
                    else:
                        # Attribute binding (preventing cross-shop values)
                        numbers = re.findall(r"(\d+(?:\.\d+)?)\s*(?:公里|km)", clause)
                        for num in numbers:
                            if dist_km is not None and abs(float(num) - float(dist_km)) > 0.05:
                                violations.append("unsupported_distance")

                # Validate Price Claims
                if any(x in clause for x in ["价格", "人均", "消费", "元"]):
                    if is_price_unknown:
                        violations.extend(["unknown_as_false", "unsupported_price"])
                    elif is_price_failed:
                        violations.extend(["tool_failure_as_fact", "unsupported_price"])
                    else:
                        # Attribute binding
                        numbers = re.findall(r"(\d+)\s*元", clause)
                        for num in numbers:
                            if avg_price is not None and abs(int(num) - int(avg_price)) > 1:
                                violations.append("unsupported_price")

                # Validate Rating Claims
                if any(x in clause for x in ["评分", "口碑", "分"]):
                    if is_rating_unknown:
                        violations.extend(["unknown_as_false", "unsupported_rating"])
                    elif is_rating_failed:
                        violations.extend(["tool_failure_as_fact", "unsupported_rating"])
                    else:
                        # Attribute binding
                        numbers = re.findall(r"(\d+\.\d+)\s*分|评分\s*(\d+\.\d+)", clause)
                        ratings = [r[0] or r[1] for r in numbers if r[0] or r[1]]
                        for r in ratings:
                            if rating is not None and abs(float(r) - float(rating)) > 0.05:
                                violations.append("unsupported_rating")

        # Global unknown_as_false fallback matching
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

        if coupon_unknown:
            negative_coupon_phrases = ["没有券", "肯定没券", "无券", "没有可用券", "暂无可用券", "没有优惠券", "暂无优惠券"]
            for phrase in negative_coupon_phrases:
                if phrase in response_text:
                    violations.extend(["unknown_as_false", "unsupported_coupon"])
                    break

        if open_status_unknown:
            negative_open_phrases = ["一定关门", "肯定打烊", "已打烊", "不营业", "关门了", "没营业", "没有开门"]
            for phrase in negative_open_phrases:
                if phrase in response_text:
                    violations.extend(["unknown_as_false", "unsupported_open_status"])
                    break

        # --- 3. 排序防篡改 (ranking_changed / winner_changed_by_llm) ---
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

        # --- 4. 对比 winner evidence 校验 ---
        # Matrix Winner check
        if plan.answer_type == "comparison":
            # Check if LLM claims X is better in price/distance/coupon/open_status
            dim_keywords = {
                "rating": ["评分更高", "口碑更好", "评分领先", "口碑领先"],
                "distance": ["更近", "走得最少", "距离领先", "近一点"],
                "open_status": ["营业", "没打烊"],
                "coupon": ["更省钱", "优惠更大", "有券", "优惠领先", "折扣更大"]
            }
            
            # Map best_for to actual dimension winners
            best_for_shops = {}
            for label, item in plan.best_for.items():
                sname = item.get("shop_name", "")
                if sname:
                    best_for_shops[label] = sname
            
            # E.g., if clause says "A 距离更近" but distance winner is B, raise violation
            for dim, keywords in dim_keywords.items():
                dim_winner_name = None
                for label, sname in best_for_shops.items():
                    if dim == "distance" and "距离" in label:
                        dim_winner_name = sname
                    elif dim == "rating" and "评分" in label:
                        dim_winner_name = sname
                    elif dim == "open_status" and "营业" in label:
                        dim_winner_name = sname
                    elif dim == "coupon" and "省钱" in label:
                        dim_winner_name = sname
                
                # Check response keywords
                for keyword in keywords:
                    if keyword in response_text:
                        # Find which shop is claimed as winner
                        for name in target_by_name.keys():
                            if name in response_text and keyword in response_text:
                                # Ensure it matches allowed winner
                                if dim_winner_name and name not in dim_winner_name and dim_winner_name not in name:
                                    violations.append("unsupported_comparison_winner")
                                    violations.append("comparison_matrix_mismatch")

        # --- 5. omitted targets 校验 ---
        for claim in plan.forbidden_claims:
            if claim in response_text:
                violations.append("forbidden_claim_violation")

        if plan.omitted_targets:
            forbidden_phrases = ["对比了所有", "对比了全部", "分析了全部", "分析了所有", "对比了全部几家", "对比了全部店"]
            for phrase in forbidden_phrases:
                if phrase in response_text:
                    violations.extend(["omitted_targets_violation", "all_targets_claim_violation"])

        # Deduplicate violations
        unique_violations = []
        for v in violations:
            if v not in unique_violations:
                unique_violations.append(v)

        passed = len(unique_violations) == 0
        return {
            "passed": passed,
            "violations": unique_violations,
            "violation": unique_violations[0] if unique_violations else None,
        }
