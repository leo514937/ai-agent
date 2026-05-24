from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

try:
    from fastapi import APIRouter, FastAPI, HTTPException
    from fastapi.responses import StreamingResponse
except ImportError:
    @dataclass
    class _StubRoute:
        path: str
        methods: Set[str]
        endpoint: Callable[..., Any]
        name: str

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: Any) -> None:
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class APIRouter:
        def __init__(self) -> None:
            self.routes: List[_StubRoute] = []

        def _register(
            self,
            path: str,
            methods: Iterable[str],
            endpoint: Callable[..., Any],
        ) -> _StubRoute:
            route = _StubRoute(
                path=path,
                methods={method.upper() for method in methods},
                endpoint=endpoint,
                name=getattr(endpoint, "__name__", "endpoint"),
            )
            self.routes.append(route)
            return route

        def post(self, path: str, **_: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            def decorator(endpoint: Callable[..., Any]) -> Callable[..., Any]:
                self._register(path, ["POST"], endpoint)
                return endpoint

            return decorator

        def get(self, path: str, **_: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            def decorator(endpoint: Callable[..., Any]) -> Callable[..., Any]:
                self._register(path, ["GET"], endpoint)
                return endpoint

            return decorator

        def include_router(self, router: "APIRouter") -> None:
            self.routes.extend(router.routes)

    class FastAPI(APIRouter):
        def __init__(self, **_: Any) -> None:
            super().__init__()
            self.state = SimpleNamespace()

    class StreamingResponse:
        def __init__(
            self,
            content: Iterable[str],
            media_type: Optional[str] = None,
            headers: Optional[Dict[str, str]] = None,
            status_code: int = 200,
        ) -> None:
            self.body_iterator = content
            self.media_type = media_type
            self.headers = headers or {}
            self.status_code = status_code
