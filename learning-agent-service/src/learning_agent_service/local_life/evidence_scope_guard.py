from __future__ import annotations

from typing import Any, Mapping, Sequence


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dict(dumped)
    return {}


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
    ) -> list[Any]:
        allowed = cls.allowed_shop_ids(ranked_candidates=ranked_candidates, evidence_pack=evidence_pack)
        if not allowed:
            return list(evidence_claims)
        filtered: list[Any] = []
        for item in evidence_claims:
            item_map = _as_mapping(item)
            shop_id = _shop_id(item_map.get("shop_id") or _as_mapping(item_map.get("metadata")).get("shop_id"))
            if shop_id is None or shop_id in allowed:
                filtered.append(item)
        return filtered

