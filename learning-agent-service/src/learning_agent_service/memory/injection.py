from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from learning_agent_service.domain.memory import (
    MemoryInjectionPlan,
    MemoryRecord,
    RetrievedMemoryPack,
)


@dataclass(frozen=True)
class MemoryInjectionPolicyConfig:
    prompt_limit: int = 4
    state_limit: int = 8
    tool_limit: int = 4
    rag_limit: int = 6
    semantic_limit: int = 6
    episodic_limit: int = 3
    procedural_limit: int = 3
    token_budget: int = 1200


@dataclass
class MemoryInjectionPolicy:
    config: MemoryInjectionPolicyConfig = field(default_factory=MemoryInjectionPolicyConfig)

    def build(self, pack: RetrievedMemoryPack) -> MemoryInjectionPlan:
        prompt = self._dedupe(self._priority_slice(pack.prompt_memories, self.config.prompt_limit))
        state = self._dedupe(self._priority_slice(pack.state_memories, self.config.state_limit))
        semantic_source = self._dedupe([*pack.semantic_memories, *pack.rag_memories])
        procedural_source = self._dedupe([*pack.procedural_memories, *pack.tool_memories])
        semantic = self._dedupe(self._priority_slice(semantic_source, self.config.semantic_limit))
        episodic = self._dedupe(self._priority_slice(pack.episodic_memories, self.config.episodic_limit))
        procedural = self._dedupe(self._priority_slice(procedural_source, self.config.procedural_limit))
        tool = self._dedupe(self._priority_slice(procedural, self.config.tool_limit))
        rag = self._dedupe(self._priority_slice(semantic, self.config.rag_limit))
        hidden_trace = self._dedupe(pack.excluded_memories[:2])
        prompt = self._apply_budget(prompt, budget=self.config.token_budget // 5)
        state = self._apply_budget(state, budget=self.config.token_budget // 4)
        semantic = self._apply_budget(semantic, budget=self.config.token_budget // 4)
        episodic = self._apply_budget(episodic, budget=self.config.token_budget // 6)
        procedural = self._apply_budget(procedural, budget=self.config.token_budget // 6)
        tool = self._apply_budget(tool, budget=self.config.token_budget // 6)
        rag = self._apply_budget(rag, budget=self.config.token_budget // 4)
        return MemoryInjectionPlan(
            prompt_memories=prompt,
            state_memories=state,
            tool_memories=tool,
            semantic_memories=semantic,
            episodic_memories=episodic,
            procedural_memories=procedural,
            rag_memories=rag,
            hidden_trace_memories=hidden_trace,
            token_budget=self.config.token_budget,
        )

    @staticmethod
    def _priority_slice(records: Sequence[MemoryRecord], limit: int) -> list[MemoryRecord]:
        ordered = sorted(records, key=lambda item: (item.importance, item.confidence, item.updated_at), reverse=True)
        return list(ordered[:limit])

    @staticmethod
    def _dedupe(records: Sequence[MemoryRecord]) -> list[MemoryRecord]:
        seen: set[str] = set()
        unique: list[MemoryRecord] = []
        for record in records:
            if record.memory_id in seen:
                continue
            seen.add(record.memory_id)
            unique.append(record)
        return unique

    @staticmethod
    def _apply_budget(records: Sequence[MemoryRecord], *, budget: int) -> list[MemoryRecord]:
        selected: list[MemoryRecord] = []
        total = 0
        for record in records:
            cost = max(8, len(f"{record.summary or ''} {record.content}") // 4 + 1)
            if selected and total + cost > budget:
                break
            selected.append(record)
            total += cost
        return selected
