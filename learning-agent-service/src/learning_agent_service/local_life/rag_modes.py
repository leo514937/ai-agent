from __future__ import annotations

from .schemas import EvidenceClaim


class ShopGroupEvidence:
    def __init__(self, shop_id: int, shop_name: str, claims: list[EvidenceClaim]):
        self.shop_id = shop_id
        self.shop_name = shop_name
        self.claims = claims
