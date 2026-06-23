"""Java backend HTTP client — thin wrapper around ``httpx.AsyncClient``.

Maps tool names to Java REST endpoints and handles serialisation,
HTTP errors, and network exceptions.  The caller (JavaToolExecutor)
receives parsed ``RawToolResult`` and never touches HTTP directly.

Endpoint configuration is centralised here so that changing the
Java API contract requires touching exactly one dictionary.
"""

from __future__ import annotations

from typing import Any

import httpx

from .. import config

# ═══════════════════════════════════════════════════════════════════
# Endpoint mapping  —  6 registered tools → Java REST paths
# ═══════════════════════════════════════════════════════════════════

JAVA_TOOL_ENDPOINTS: dict[str, str] = {
    "resolve_shop": "/internal/agent/tools/resolve-shop",
    "search_shops": "/internal/agent/tools/search-shops",
    "get_shop_detail": "/internal/agent/tools/shops/{shop_id}",
    "get_coupon_list": "/internal/agent/tools/shops/{shop_id}/coupons",
    "check_open_status": "/internal/agent/tools/shops/{shop_id}/open-status",
    "get_distance_eta": "/internal/agent/tools/shops/{shop_id}/distance-eta",
    "get_shop_cards": "/internal/agent/tools/shop-cards",
    "get_shop_review_summary": "/internal/agent/tools/shop-review-summary",
    "get_deal_list": "/internal/agent/tools/shops/{shop_id}/deals",
}

_SUPPORTED_TOOLS = frozenset(JAVA_TOOL_ENDPOINTS.keys())

# Tools that use POST even when {shop_id} is present in the path
# (because they also accept a JSON request body).
_POST_METHOD_TOOLS = frozenset({
    "check_open_status",
    "get_distance_eta",
    "get_shop_cards",
    "get_shop_review_summary",
    "get_deal_list",
})


# ═══════════════════════════════════════════════════════════════════
# Public interface
# ═══════════════════════════════════════════════════════════════════


class JavaToolClient:
    """Low-level HTTP client for the Java backend.

    Usage (one per tool call is fine — the underlying AsyncClient
    connection pool is reused):

        client = JavaToolClient()
        raw, meta = await client.call("resolve_shop", {"query": "海底捞"})
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_ms: int | None = None,
    ) -> None:
        self._base_url = (base_url or config.JAVA_BACKEND_BASE_URL).rstrip("/")
        timeout = (timeout_ms or config.JAVA_BACKEND_TIMEOUT_MS) / 1000.0
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout),
        )

    async def call(
        self,
        tool_name: str,
        args: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Execute a single tool call against the Java backend.

        Args:
            tool_name: Registered tool name (see ``JAVA_TOOL_ENDPOINTS``).
            args: Arguments validated by ToolCallGateway.

        Returns:
            Tuple of (raw_result_dict, metadata_dict).
            *raw_result_dict* carries the JSON-decoded response body
            (or an error-shaped dict on failure).
            *metadata_dict* carries ``http_status``, ``endpoint``,
            and the resolved URL for debugging.

        Raises:
            TimeoutError: When the HTTP request times out.
        """
        if tool_name not in _SUPPORTED_TOOLS:
            return (
                {
                    "success": False,
                    "result_status": "unknown",
                    "data": None,
                    "error_code": "TOOL_NOT_REGISTERED",
                    "error_message": f"Tool '{tool_name}' has no Java API endpoint mapping",
                },
                {"http_status": None, "endpoint": None, "url": None},
            )

        endpoint_template = JAVA_TOOL_ENDPOINTS[tool_name]
        endpoint, method, body_args = _resolve_endpoint(tool_name, endpoint_template, args)
        url = f"{self._base_url}{endpoint}"

        try:
            if method == "GET":
                response = await self._client.get(endpoint, params=body_args)
            else:
                response = await self._client.post(endpoint, json=body_args)

            http_status = response.status_code
            metadata = {
                "http_status": http_status,
                "endpoint": endpoint,
                "url": url,
            }

            if http_status == 200:
                data = response.json()
                return (data, metadata)

            # 4xx / 5xx — map to failed / unknown
            if 400 <= http_status < 500:
                detail = _extract_error_detail(response)
                return (
                    {
                        "success": False,
                        "result_status": "failed",
                        "data": None,
                        "error_code": _http_status_to_error_code(http_status),
                        "error_message": detail or f"HTTP {http_status} from Java backend",
                    },
                    metadata,
                )

            # 5xx
            return (
                {
                    "success": False,
                    "result_status": "unknown",
                    "data": None,
                    "error_code": "BACKEND_UNAVAILABLE",
                    "error_message": f"Java backend returned HTTP {http_status}",
                },
                metadata,
            )

        except httpx.TimeoutException as exc:
            raise TimeoutError(str(exc)) from exc
        except httpx.RequestError as exc:
            return (
                {
                    "success": False,
                    "result_status": "unknown",
                    "data": None,
                    "error_code": "NETWORK_ERROR",
                    "error_message": f"Java backend unreachable: {exc}",
                },
                {"http_status": None, "endpoint": endpoint, "url": url},
            )

    async def close(self) -> None:
        await self._client.aclose()


# ═══════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════


def _resolve_endpoint(
    tool_name: str,
    template: str,
    args: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    """Build the final endpoint path, HTTP method, and body/query args.

    Templates with ``{shop_id}`` placeholders are expanded and the
    consumed argument is removed from *body_args* so it is not sent
    as a JSON/query parameter.
    """
    body_args = dict(args)
    shop_id = body_args.pop("shop_id", None)

    if "{shop_id}" in template and shop_id:
        endpoint = template.replace("{shop_id}", str(shop_id))
        if tool_name in _POST_METHOD_TOOLS:
            method = "POST"
        else:
            method = "GET"
    else:
        endpoint = template
        method = "POST"

    return endpoint, method, body_args


def _http_status_to_error_code(status: int) -> str:
    if status == 404:
        return "SHOP_NOT_FOUND"
    if status == 400:
        return "INVALID_ARGUMENT"
    return "BACKEND_UNAVAILABLE"


def _extract_error_detail(response: httpx.Response) -> str:
    """Try to extract an error message from the Java JSON response."""
    try:
        body = response.json()
        if isinstance(body, dict):
            return str(body.get("error_message") or body.get("message") or body.get("detail") or "")
    except Exception:
        pass
    return ""
