from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from learning_agent_service.memory.trace import MemoryTraceRecorder


class MemoryTraceTestCase(unittest.TestCase):
    def test_recorder_tracks_unique_memory_ids(self) -> None:
        recorder = MemoryTraceRecorder(session_id="session-1", turn_id="turn-1")
        recorder.record_retrieved(["mem-1", "mem-2", "mem-1"])
        recorder.record_injected(["mem-2", "mem-3"])
        recorder.record_skipped(["mem-4"])
        recorder.record_decision_reason("candidate-1", "higher_confidence")
        recorder.record_conflict_ids(["mem-5", "mem-6", "mem-5"])
        recorder.record_deletion_job_ids(["job-1", "job-2", "job-1"])
        recorder.record_skip_reason("candidate-2", "require_confirmation")

        trace = recorder.snapshot()
        self.assertEqual(trace.retrieved, ["mem-1", "mem-2"])
        self.assertEqual(trace.injected, ["mem-2", "mem-3"])
        self.assertEqual(trace.skipped, ["mem-4"])
        self.assertEqual(trace.candidate_ids, [])
        self.assertEqual(trace.decision_reasons["candidate-1"], "higher_confidence")
        self.assertEqual(trace.conflict_ids, ["mem-5", "mem-6"])
        self.assertEqual(trace.deletion_job_ids, ["job-1", "job-2"])
        self.assertEqual(trace.skip_reasons["candidate-2"], "require_confirmation")
        self.assertEqual(trace.total_memory_tokens, 0)
        self.assertFalse(trace.qdrant_degraded)
        self.assertTrue(trace.trace_id.startswith("memory-trace:"))


if __name__ == "__main__":
    unittest.main()
