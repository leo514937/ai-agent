from __future__ import annotations
from typing import Any, Mapping, List
from .schemas import EvidenceClaim

class ShopGroupEvidence:
    def __init__(self, shop_id: int, shop_name: str, claims: List[EvidenceClaim]):
        self.shop_id = shop_id
        self.shop_name = shop_name
        self.claims = claims
