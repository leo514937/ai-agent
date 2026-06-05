from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from learning_agent_service.domain.utils import as_mapping as _as_mapping


def _shop_id(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


class EvidenceScopeGuard:
    @staticmethod
    def allowed_shop_ids(
        *,
        ranked_candidates: Sequence[Mapping[str, Any] | Any] | None = None,
        evidence_pack: Mapping[str, Any] | Any | None = None,
    ) -> set[int]:
        ids: set[int] = set()
        for candidate in ranked_candidates or []:
            candidate_map = _as_mapping(candidate)
            shop_id = _shop_id(candidate_map.get("shop_id") or candidate_map.get("id"))
            if shop_id is not None:
                ids.add(shop_id)
        pack_map = _as_mapping(evidence_pack)
        for candidate in pack_map.get("ranked_candidates") or []:
            candidate_map = _as_mapping(candidate)
            shop_id = _shop_id(candidate_map.get("shop_id") or candidate_map.get("id"))
            if shop_id is not None:
                ids.add(shop_id)
        return ids

    @classmethod
    def filter_evidence_claims(
        cls,
        evidence_claims: Sequence[Mapping[str, Any] | Any],
        *,
        ranked_candidates: Sequence[Mapping[str, Any] | Any] | None = None,
        evidence_pack: Mapping[str, Any] | Any | None = None,
        target_shop_id: int | None = None,
    ) -> list[Any]:
        if target_shop_id is not None:
            # STRICT SINGLE SHOP MODE: ONLY allow target_shop_id evidence! Drop everything else.
            filtered: list[Any] = []
            for item in evidence_claims:
                item_map = _as_mapping(item)
                shop_id = _shop_id(item_map.get("shop_id") or _as_mapping(item_map.get("metadata")).get("shop_id"))
                if shop_id == target_shop_id:
                    filtered.append(item)
            return filtered

        allowed = cls.allowed_shop_ids(ranked_candidates=ranked_candidates, evidence_pack=evidence_pack)
        
        # Day4 strict single shop filter: if we have allowed shops, filter strictly.
        # But wait, to be extremely rigid, let's parse from ranked_candidates first.
        # If ranked_candidates is passed and has elements, we should only allow those.
        if not allowed:
            return list(evidence_claims)
        filtered: list[Any] = []
        for item in evidence_claims:
            item_map = _as_mapping(item)
            shop_id = _shop_id(item_map.get("shop_id") or _as_mapping(item_map.get("metadata")).get("shop_id"))
            # In single_shop_mode (when target_shop is set), the allowed list has exactly 1 shop_id.
            # Enforce that strictly if shop_id is not None.
            if shop_id is not None and shop_id in allowed:
                filtered.append(item)
            elif shop_id is None:
                filtered.append(item)
        return filtered


