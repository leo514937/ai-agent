from __future__ import annotations

import unittest
from types import SimpleNamespace

import _bootstrap  # noqa: F401

from learning_agent_service.config.settings_impl import Settings
from learning_agent_service.domain import MemoryRecord, MemoryScope, MemorySource, MemoryStatus, MemoryType
from learning_agent_service.local_life.schemas import LocationNorm, QueryUnderstandingResult, TimeNorm
from learning_agent_service.local_life.slot_extractor import extract_slots
from learning_agent_service.memory.conflict import ConflictResolutionAction, MemoryConflictResolver
from learning_agent_service.memory.preferences import extract_preference_signal
from learning_agent_service.memory.service import MemoryService


class PreferenceRegistryTestCase(unittest.TestCase):
    def _build_record(
        self,
        *,
        memory_id: str,
        normalized_key: str,
        normalized_value: str,
        summary: str,
    ) -> MemoryRecord:
        return MemoryRecord(
            memory_id=memory_id,
            user_id="user-1",
            session_id="session-1",
            source_session_id="session-1",
            type=MemoryType.PREFERENCE,
            scope=MemoryScope.USER,
            status=MemoryStatus.ACTIVE,
            source=MemorySource.USER_EXPLICIT,
            summary=summary,
            content={"normalized_key": normalized_key, "normalized_value": normalized_value},
            normalized_key=normalized_key,
            normalized_value=normalized_value,
            confidence=0.9,
            importance=0.8,
            stability=0.9,
            is_active=True,
            source_turn_id="turn-1",
        )

    def test_time_bound_preference_stays_session_scoped(self) -> None:
        signal = extract_preference_signal(text="今天不想吃辣", session_id="session-1", turn_id="turn-1")

        self.assertIsNotNone(signal)
        self.assertEqual(signal.preference_key, "food.spicy_preference")
        self.assertEqual(signal.current_value, "avoid_spicy_temporarily")
        self.assertEqual(signal.persistence_scope.value, "session")
        self.assertFalse(signal.should_update_profile)

    def test_multi_key_conflict_is_key_scoped(self) -> None:
        resolver = MemoryConflictResolver()
        spicy_existing = self._build_record(
            memory_id="spicy-old",
            normalized_key="food.spicy_preference",
            normalized_value="likes_spicy",
            summary="我爱吃辣",
        )
        budget_existing = self._build_record(
            memory_id="budget-old",
            normalized_key="dining.budget_per_person",
            normalized_value="100",
            summary="人均100",
        )
        budget_candidate = self._build_record(
            memory_id="budget-new",
            normalized_key="dining.budget_per_person",
            normalized_value="150",
            summary="人均150",
        )

        unrelated_decision = resolver.resolve_preference_change(
            budget_candidate,
            [spicy_existing],
            temporal_scope="long_term",
        )
        conflicted_decision = resolver.resolve_preference_change(
            budget_candidate,
            [budget_existing],
            temporal_scope="long_term",
        )

        self.assertEqual(unrelated_decision.action, ConflictResolutionAction.INSERT_NEW)
        self.assertEqual(conflicted_decision.action, ConflictResolutionAction.SUPERSEDE_OLD_INSERT_NEW)
        self.assertEqual(conflicted_decision.old_memory_id, "budget-old")

    def test_current_profile_projection_flows_into_local_life_context(self) -> None:
        projection_store = SimpleNamespace(
            list_active=lambda user_id: [
                SimpleNamespace(preference_key="food.spicy_preference", current_value="no_spicy"),
                SimpleNamespace(preference_key="answer_style.preference", current_value="concise"),
            ]
        )
        service = MemoryService(
            session_store=SimpleNamespace(load=lambda *args, **kwargs: None, save=lambda *args, **kwargs: None, load_any=lambda *args, **kwargs: None),
            async_log_store=SimpleNamespace(append=lambda *args, **kwargs: None),
            settings=Settings(prefer_real_adapters=False, allow_in_memory_fallback=True),
            profile_projection_store=projection_store,
        )

        profile = service._preference_profile("user-1", {})
        diagnostics = profile.extra["preference_profile_diagnostics"]
        understanding = QueryUnderstandingResult(
            normalized_query="??????",
            semantic_query="??????",
            keyword_query="??",
            time_norm=TimeNorm(),
            location_norm=LocationNorm(),
        )

        slots, _, _ = extract_slots(
            understanding,
            "??????",
            session_context=profile.extra,
            model_hint={},
        )

        self.assertIn("spicy", slots.avoid)
        self.assertEqual(profile.extra["local_life_avoid"], ["spicy"])
        self.assertEqual(profile.extra["preferred_output_style"], "concise")
        self.assertEqual(diagnostics["profile_projection_store"]["state"], "loaded")
        self.assertEqual(diagnostics["profile_projection_store"]["count"], 2)
        self.assertEqual(diagnostics["preference_store"]["state"], "unavailable")



    def test_preference_profile_exposes_diagnostics_for_store_errors(self) -> None:
        projection_store = SimpleNamespace(list_active=lambda user_id: (_ for _ in ()).throw(RuntimeError("projection failed")))
        preference_store = SimpleNamespace(get=lambda user_id: (_ for _ in ()).throw(RuntimeError("preference failed")))
        service = MemoryService(
            session_store=SimpleNamespace(load=lambda *args, **kwargs: None, save=lambda *args, **kwargs: None, load_any=lambda *args, **kwargs: None),
            async_log_store=SimpleNamespace(append=lambda *args, **kwargs: None),
            settings=Settings(prefer_real_adapters=False, allow_in_memory_fallback=True),
            profile_projection_store=projection_store,
            preference_store=preference_store,
        )

        profile = service._preference_profile("user-1", {})
        diagnostics = profile.extra["preference_profile_diagnostics"]

        self.assertEqual(diagnostics["profile_projection_store"]["state"], "error")
        self.assertEqual(diagnostics["preference_store"]["state"], "error")


if __name__ == "__main__":
    unittest.main()
