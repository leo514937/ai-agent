package com.hmdp.ai.runtime;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertNotNull;

class AiTurnRegistryTest {

    @Test
    void shouldTrackStatusTransitionsAndPreserveCancelReason() {
        AiTurnRegistry registry = new AiTurnRegistry();

        AiTurnRuntimeRecord started = registry.startTurn("session-1", "turn-1", "trace-1");
        assertEquals(AiTurnStatus.RUNNING, started.getStatus());

        registry.markClientDisconnected("session-1", "turn-1");
        assertEquals(AiTurnStatus.CLIENT_DISCONNECTED, registry.get("session-1", "turn-1").getStatus());

        registry.markFinished("session-1", "turn-1", "最终答案");
        assertEquals(AiTurnStatus.FINISHED, registry.get("session-1", "turn-1").getStatus());
        assertEquals("最终答案", registry.get("session-1", "turn-1").getFinalAnswer());

        registry.startTurn("session-2", "turn-2", "trace-2");
        registry.markUserCancelled("session-2", "turn-2", "user_stop");
        AiTurnRuntimeRecord cancelled = registry.get("session-2", "turn-2");
        assertNotNull(cancelled);
        assertEquals(AiTurnStatus.USER_CANCELLED, cancelled.getStatus());
        assertEquals("user_stop", cancelled.getCancelReason());

        registry.markFinished("session-2", "turn-2", "不会覆盖");
        assertEquals(AiTurnStatus.USER_CANCELLED, registry.get("session-2", "turn-2").getStatus());
    }

    @Test
    void shouldRejectSecondRunningTurnInSameSession() {
        AiTurnRegistry registry = new AiTurnRegistry();
        registry.startTurn("session-3", "turn-1", "trace-1");
        assertThrows(IllegalStateException.class, () -> registry.startTurn("session-3", "turn-2", "trace-2"));
    }
}
