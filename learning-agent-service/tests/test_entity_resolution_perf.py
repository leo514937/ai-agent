"""Performance smoke test for entity resolution pipeline.

Verifies the full decompose → recall → bind chain completes within
acceptable latency (50ms p99 with mocked Java backend).
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

from learning_agent_service.local_life.entity_decomposer import decompose_shop_query
from learning_agent_service.local_life.recall_service import recall_candidates
from learning_agent_service.local_life.shop_binding import bind_shop_id
from learning_agent_service.local_life.schemas import ShopRecord


def _make_shop(shop_id: int, name: str, area: str | None = None) -> ShopRecord:
    return ShopRecord(id=shop_id, name=name, area=area, source="java")


def _mock_client(shops: list[ShopRecord] | None = None) -> MagicMock:
    client = MagicMock()
    client.get_brand_list.return_value = ["海底捞", "新白鹿", "外婆家"]
    client.get_area_list.return_value = ["水晶城", "万达", "乐堤港"]
    client.search_shops_by_name.return_value = shops or []
    return client


def test_entity_resolution_chain_latency():
    """Full chain: decompose → recall → bind completes within 50ms (mocked backend)."""
    shops = [_make_shop(5, "海底捞火锅(水晶城店)", area="水晶城")]
    client = _mock_client(shops)
    queries = [
        "海底捞水晶城怎么样",
        "新白鹿哪家好吃",
        "火锅推荐",
        "外婆家有券吗",
        "某不存在的店",
    ]

    iterations = 100
    start = time.perf_counter()
    for _ in range(iterations):
        for query in queries:
            entity = decompose_shop_query(query)
            result = recall_candidates(client, entity)
            bind_shop_id(result, allow_clarification=True)
    elapsed_ms = (time.perf_counter() - start) * 1000
    per_call_ms = elapsed_ms / (iterations * len(queries))

    # Should be well under 50ms per call with mocked backend
    assert per_call_ms < 50, f"Entity resolution too slow: {per_call_ms:.2f}ms per call"
