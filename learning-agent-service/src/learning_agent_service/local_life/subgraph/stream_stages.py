from typing import Any, Iterable, Sequence

from .helpers import *
from .stream_context import StreamRunContext
from .stream_compose import LocalLifeStreamComposeMixin
from .stream_load import LocalLifeStreamLoadMixin
from .stream_retrieve import LocalLifeStreamRetrieveMixin
from .stream_route import LocalLifeStreamRouteMixin
from ...tools.orchestrator import _StreamEventRelay, _is_clarification_kind, _map_status  # noqa: F401


class LocalLifeSubgraphRunMixin(
    LocalLifeStreamLoadMixin,
    LocalLifeStreamRouteMixin,
    LocalLifeStreamRetrieveMixin,
    LocalLifeStreamComposeMixin,
):
    def run_stream(
        self,
        command: ChatTurnCommand,
        persistent_context: PersistentSessionContext | None = None,
    ) -> Iterable[SseEnvelope]:
        ctx = yield from self._build_stream_run_context(command=command, persistent_context=persistent_context)
        bundle = yield from self._stage_load_and_understand(ctx)
        if bundle is not None:
            return
        bundle = yield from self._stage_route_and_clarify(ctx)
        if bundle is not None:
            return
        yield from self._stage_retrieve_and_tools(ctx)
        yield from self._stage_compose_and_finalize(ctx)

