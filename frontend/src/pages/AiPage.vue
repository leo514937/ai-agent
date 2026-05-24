<template>
  <section class="assistant-page slide-up">
    <!-- The "Canvas" - A distinct background to show it's separate from the chat -->
    <div class="assistant-page__canvas">
    </div>

    <div class="assistant-page__shell">
      <div class="assistant-page__floating-chat" :class="{ 'is-empty': messages.length === 0 }">
        <div v-show="messages.length" ref="scrollRef" class="assistant-page__viewport" @scroll="handleScroll">
          <div class="assistant-page__stream">
            <AssistantMessage
              v-for="message in messages"
              :key="message.id"
              :message="message"
              class="assistant-page__message"
              @approval="handleApproval"
              @typewrite="handleTypewrite"
            />
          </div>
        </div>

        <footer class="assistant-page__footer">
          <button
            v-show="showJumpToLatest"
            class="assistant-page__jump"
            type="button"
            aria-label="回到最新"
            @click="jumpToLatest"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 4v16m0 0l-6-6m6 6l6-6" />
            </svg>
          </button>

          <div v-if="messages.length === 0" class="assistant-page__hero">
            <h2>你今天在想些什么？</h2>
          </div>

          <div class="assistant-page__composer">
            <AssistantComposer
              v-model="draft"
              :loading="sending"
              :streaming="isAssistantStreaming"
              :suggestions="composerSuggestions"
              :hint="messages.length === 0 ? '' : 'ENTER 发送 · SHIFT+ENTER 换行'"
              @submit="handleSubmit"
              @pick="handleComposerPick"
              @stop="handleStopGeneration"
            />
          </div>
        </footer>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import AssistantComposer from '@/components/assistant/AssistantComposer.vue';
import AssistantMessage from '@/components/assistant/AssistantMessage.vue';
import {
  ASSISTANT_STATE_EVENT,
  appendSessionMessage,
  updateSessionMessage,
} from '@/lib/assistant-store.js';
import {
  buildAssistantMessagePayload,
  normalizeAssistantNextSteps,
  normalizeAssistantSuggestions,
  splitAssistantMessageContent,
} from '@/lib/assistant.js';
import { streamAssistantPrompt, submitAssistantApproval } from '@/lib/catalog.js';

import { useChatSession } from '@/composables/useChatSession.js';
import { useChatScroll } from '@/composables/useChatScroll.js';

const route = useRoute();

const draft = ref('');
const sending = ref(false);
const activeStreamController = ref(null);
const isAssistantStreaming = computed(() => Boolean(activeStreamController.value));
const raf = typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function'
  ? window.requestAnimationFrame.bind(window)
  : (cb) => window.setTimeout(cb, 16);
const caf = typeof window !== 'undefined' && typeof window.cancelAnimationFrame === 'function'
  ? window.cancelAnimationFrame.bind(window)
  : (id) => window.clearTimeout(id);

const { 
  sessions, 
  activeSessionId, 
  currentSession, 
  loadSessionsFromStorage, 
  persistSession, 
  ensureCurrentSession 
} = useChatSession();

let pendingPersistSession = null;
let pendingPersistFrame = 0;
let pendingTypewriteFrame = 0;

function flushPendingPersistSession() {
  if (!pendingPersistSession) {
    return;
  }

  const session = pendingPersistSession;
  pendingPersistSession = null;
  if (pendingPersistFrame) {
    caf(pendingPersistFrame);
    pendingPersistFrame = 0;
  }
  persistSession(session);
}

function queuePersistSession(session, { immediate = false } = {}) {
  pendingPersistSession = session;

  if (immediate) {
    flushPendingPersistSession();
    return;
  }

  if (pendingPersistFrame) {
    return;
  }

  pendingPersistFrame = raf(() => {
    pendingPersistFrame = 0;
    flushPendingPersistSession();
  });
}

const messages = computed(() => {
  const list = currentSession.value?.messages || [];
  return list.filter((msg) => {
    if (msg.role !== 'system') {
      return true;
    }
    
    // Always keep interactive cards or explicit error/cancellation events
    if (['error', 'clarification_card', 'approval_required', 'cancelled'].includes(msg.eventType)) {
      return true;
    }
    
    // Keep messages that sound like errors
    if (msg.content && (msg.content.includes('抱歉') || msg.content.includes('失败') || msg.content.includes('不可用') || msg.content.includes('异常') || msg.content.match(/500|404|failed/i))) {
      return true;
    }
    
    // Hide all other system messages (like progress bubbles from chat history)
    return false;
  });
});

const {
  scrollRef,
  stickToBottom,
  showJumpToLatest,
  handleScroll,
  scrollToLatest,
  jumpToLatest
} = useChatScroll(messages);

const latestAssistantMessage = computed(() => {
  return messages.value
    .slice()
    .reverse()
    .find((message) => message.role === 'assistant') || null;
});

const composerSuggestions = computed(() => {
  const assistantSuggestions = normalizeAssistantSuggestions(latestAssistantMessage.value?.suggestions || []);
  if (assistantSuggestions.length) {
    return assistantSuggestions.slice(0, 3);
  }

  return normalizeAssistantNextSteps(latestAssistantMessage.value?.nextSteps || [])
    .slice(0, 3)
    .map((item) => ({
      label: item,
      prompt: item,
      icon: '',
      key: item,
    }));
});

function clearActiveStreamController(controller) {
  if (activeStreamController.value === controller) {
    activeStreamController.value = null;
  }
}

function markStreamCancelled(latestSession, assistantMessageId) {
  let nextSession = latestSession;
  if (assistantMessageId) {
    nextSession = updateSessionMessage(nextSession, assistantMessageId, (message) => ({
      ...message,
      streaming: false,
      cancelled: true,
      cancelledAt: new Date().toISOString(),
    }));
  } else {
    nextSession = appendSessionMessage(nextSession, {
      role: 'system',
      content: '已停止生成。',
      eventType: 'cancelled',
      cancelled: true,
      source: 'local',
    });
  }

  persistSession(nextSession);
  return nextSession;
}

async function runAssistantStream(workingSession, payload, { signal } = {}) {
  let latestSession = workingSession;
  let assistantMessageId = '';
  const response = await streamAssistantPrompt(
    payload,
    {
      async onDelta(entry) {
        if (signal?.aborted) {
          return;
        }
        const partialAnswer = String(entry?.payload?.answer_text ?? entry?.payload?.delta ?? '');
        if (!partialAnswer.trim()) {
          return;
        }
        const partialParts = splitAssistantMessageContent(partialAnswer);
        const nextAnswerContent = partialParts.answerContent || '';
        const nextThinkingContent = partialParts.thinkingContent || '';

        if (!assistantMessageId) {
          latestSession = appendSessionMessage(latestSession, {
            role: 'assistant',
            content: nextAnswerContent,
            answer: nextAnswerContent,
            answerContent: nextAnswerContent,
            thinkingContent: nextThinkingContent,
            rawContent: partialAnswer,
            mode: 'streaming',
            source: 'learning-agent-service',
            fallback: false,
            eventType: entry.type,
            eventTimeline: [entry],
            traceId: entry.traceId,
            turnId: entry.turnId,
            sessionId: entry.sessionId,
            streaming: true,
          });
          assistantMessageId = latestSession.messages[latestSession.messages.length - 1]?.id || '';
        } else {
          latestSession = updateSessionMessage(latestSession, assistantMessageId, (message) => ({
            ...message,
            content: nextAnswerContent,
            answer: nextAnswerContent,
            answerContent: nextAnswerContent,
            thinkingContent: nextThinkingContent || message.thinkingContent || '',
            rawContent: partialAnswer,
            eventType: entry.type,
            eventTimeline: [...(message.eventTimeline || []), entry],
            traceId: entry.traceId || message.traceId,
            turnId: entry.turnId || message.turnId,
            sessionId: entry.sessionId || message.sessionId,
            streaming: true,
          }));
        }
        queuePersistSession(latestSession);
        if (stickToBottom.value) await scrollToLatest({ behavior: 'auto' });
      },
      async onProgress(message, entry) {
        if (signal?.aborted) {
          return;
        }

        const isInteractive = entry && (entry.type === 'clarification_card' || entry.type === 'approval_required' || entry.type === 'error');

        if (!isInteractive && entry) {
          if (!assistantMessageId) {
            latestSession = appendSessionMessage(latestSession, {
              role: 'assistant',
              content: '',
              answer: '',
              answerContent: '',
              thinkingContent: '',
              rawContent: '',
              mode: 'streaming',
              source: 'learning-agent-service',
              fallback: false,
              eventType: entry.type,
              eventTimeline: [entry],
              traceId: entry.traceId,
              turnId: entry.turnId,
              sessionId: entry.sessionId,
              streaming: true,
            });
            assistantMessageId = latestSession.messages[latestSession.messages.length - 1]?.id || '';
          } else {
            latestSession = updateSessionMessage(latestSession, assistantMessageId, (msg) => ({
              ...msg,
              eventType: entry.type,
              eventTimeline: [...(msg.eventTimeline || []), entry],
            }));
          }
          queuePersistSession(latestSession);
          return;
        }

        latestSession = appendSessionMessage(latestSession, message);
        queuePersistSession(latestSession);
      },
      async onFinal(message) {
        if (signal?.aborted) {
          return;
        }
        if (assistantMessageId) {
          latestSession = updateSessionMessage(latestSession, assistantMessageId, (current) => ({
            ...current,
            ...message,
            content: message.content || current.content || current.answerContent || '',
            answer: message.answer || message.answerContent || current.answer || current.answerContent || '',
            answerContent: message.answerContent || message.answer || current.answerContent || current.answer || '',
            thinkingContent: message.thinkingContent || current.thinkingContent || '',
            rawContent: message.rawContent || current.rawContent || message.content || current.content || '',
            streaming: false,
          }));
        } else {
          latestSession = appendSessionMessage(latestSession, message);
          assistantMessageId = latestSession.messages[latestSession.messages.length - 1]?.id || '';
        }
        queuePersistSession(latestSession, { immediate: true });
      },
      async onError(message) {
        if (signal?.aborted) {
          return;
        }
        latestSession = appendSessionMessage(latestSession, message);
        queuePersistSession(latestSession, { immediate: true });
      },
    },
    { signal }
  );
  flushPendingPersistSession();
  if (response.cancelled || signal?.aborted) {
    latestSession = markStreamCancelled(latestSession, assistantMessageId);
    return {
      ...response,
      cancelled: true,
      session: latestSession,
    };
  }
  return {
    ...response,
    session: latestSession,
  };
}

async function handleSubmit(content) {
  const text = String(content || '').trim();
  if (!text || sending.value || isAssistantStreaming.value) {
    return;
  }

  const streamController = new AbortController();
  activeStreamController.value = streamController;
  sending.value = true;

  try {
    const session = await ensureCurrentSession();
    let workingSession = appendSessionMessage(session, { role: 'user', content: text });
    persistSession(workingSession);
    draft.value = '';
    await scrollToLatest({ behavior: 'auto' });

    const payload = buildAssistantMessagePayload(text, {
      ...workingSession.context,
      page: workingSession.page || 'ai',
    });
    const response = await runAssistantStream(workingSession, {
      ...payload,
      sessionId: workingSession.id,
    }, { signal: streamController.signal });
    workingSession = response.session || workingSession;
    flushPendingPersistSession();

    if (response.cancelled) {
      return;
    }

    if (!response.final && !response.error && response.terminalType !== 'clarification_card') {
      const failedSession = appendSessionMessage(workingSession, {
        role: 'system',
        content: '抱歉，当前 AI 服务没有返回可用结果，请稍后再试。',
      });
      persistSession(failedSession);
    }
  } catch (error) {
    if (streamController.signal.aborted) {
      return;
    }
    console.error('AI 对话发送失败', error);
    if (currentSession.value) {
      const detail = error instanceof Error && error.message ? `：${error.message}` : '';
      const failedSession = appendSessionMessage(currentSession.value, {
        role: 'system',
        content: `抱歉，当前 AI 服务暂时不可用，请稍后再试${detail}`,
      });
      persistSession(failedSession);
    }
  } finally {
    clearActiveStreamController(streamController);
    sending.value = false;
  }
}

function handleStopGeneration() {
  const controller = activeStreamController.value;
  if (!controller || controller.signal.aborted) {
    return;
  }

  controller.abort();
}

async function handleApproval(payload) {
  if (!payload?.sessionId || sending.value) {
    return;
  }

  const streamController = new AbortController();
  activeStreamController.value = streamController;
  sending.value = true;
  try {
    const session = sessions.value.find((item) => item.id === payload.sessionId);
    if (!session) {
      return;
    }

    let workingSession = appendSessionMessage(session, {
      role: 'user',
      content: payload.decision === 'approved' ? '确认继续执行' : '先不执行',
    });
    persistSession(workingSession);

    await submitAssistantApproval({
      userId: 'guest',
      user_id: 'guest',
      sessionId: payload.sessionId,
      session_id: payload.sessionId,
      traceId: payload.traceId || '',
      trace_id: payload.traceId || '',
      turnId: payload.turnId || '',
      turn_id: payload.turnId || '',
      approvalId: payload.approvalId || '',
      approval_id: payload.approvalId || '',
      decision: payload.decision,
      approvalRequest: payload.approvalRequest || {},
      approval_request: payload.approvalRequest || {},
    });

    const response = await runAssistantStream(workingSession, {
      ...buildAssistantMessagePayload(
        payload.decision === 'approved' ? '确认继续执行' : '先不执行',
        {
          ...workingSession.context,
          page: workingSession.page || 'ai',
        },
      ),
      sessionId: payload.sessionId,
      traceId: payload.traceId || '',
      approvalRequest: payload.approvalRequest || {},
      approval_request: payload.approvalRequest || {},
    }, { signal: streamController.signal });
    workingSession = response.session || workingSession;

    if (response.cancelled) {
      return;
    }

    if (!response.final && !response.error && response.terminalType !== 'clarification_card') {
      workingSession = appendSessionMessage(workingSession, {
        role: 'system',
        content: '审批结果已提交，但本轮没有返回新的执行结果。',
      });
      persistSession(workingSession);
    }
    if (stickToBottom.value) await scrollToLatest({ behavior: 'auto' });
  } catch (error) {
    if (streamController.signal.aborted) {
      return;
    }
    console.error('AI 审批处理失败', error);
    const session = sessions.value.find((item) => item.id === payload.sessionId);
    if (session) {
      const detail = error instanceof Error && error.message ? `：${error.message}` : '';
      persistSession(appendSessionMessage(session, {
        role: 'system',
        content: `审批提交失败，请稍后再试${detail}`,
      }));
      if (stickToBottom.value) await scrollToLatest({ behavior: 'auto' });
    }
  } finally {
    clearActiveStreamController(streamController);
    sending.value = false;
  }
}

function handleTypewrite() {
  if (!stickToBottom.value || pendingTypewriteFrame) {
    return;
  }

  pendingTypewriteFrame = raf(() => {
    pendingTypewriteFrame = 0;
    if (stickToBottom.value) {
      scrollToLatest({ behavior: 'auto' });
    }
  });
}

function handleAssistantStateChange() {
  loadSessionsFromStorage();
}

function handleComposerPick(prompt) {
  draft.value = String(prompt || '');
}

onBeforeUnmount(() => {
  if (pendingPersistFrame) {
    caf(pendingPersistFrame);
    pendingPersistFrame = 0;
  }
  if (pendingTypewriteFrame) {
    caf(pendingTypewriteFrame);
    pendingTypewriteFrame = 0;
  }
  pendingPersistSession = null;
});

watch(
  () => route.query.id,
  () => {
    loadSessionsFromStorage();
  },
  { immediate: true },
);

watch(
  activeSessionId,
  async (next, prev) => {
    if (!next || next === prev) {
      return;
    }

    await scrollToLatest({ behavior: 'auto' });
  },
  { immediate: true },
);

watch(
  () => messages.value.length,
  async (next, prev) => {
    if (next === prev || !stickToBottom.value) {
      return;
    }

    await scrollToLatest({ behavior: 'auto' });
  },
  { flush: 'post' },
);

onMounted(() => {
  scrollToLatest({ behavior: 'auto' });
  window.addEventListener(ASSISTANT_STATE_EVENT, handleAssistantStateChange);
});

onBeforeUnmount(() => {
  activeStreamController.value?.abort();
  activeStreamController.value = null;
  window.removeEventListener(ASSISTANT_STATE_EVENT, handleAssistantStateChange);
});
</script>

<style scoped>
.assistant-page {
  position: relative;
  height: 100%;
  overflow: hidden;
  color: var(--text);
  background: var(--bg);
}

.assistant-page__canvas {
  position: absolute;
  inset: 0;
  background-image: 
    linear-gradient(var(--line) 1px, transparent 1px),
    linear-gradient(90deg, var(--line) 1px, transparent 1px);
  background-size: 32px 32px;
  opacity: 0.15;
  pointer-events: none;
}

.assistant-page__canvas-label {
  position: absolute;
  top: 24px;
  left: 24px;
  font-size: 0.7rem;
  font-weight: 900;
  color: var(--muted);
  letter-spacing: 0.2em;
}

.assistant-page__shell {
  position: relative;
  height: 100%;
  display: flex;
  flex-direction: column;
  z-index: 10;
}

.assistant-page__floating-chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  padding: 0;
  height: 100%;
  position: relative; /* anchor for absolutely-positioned footer/composer */
}

.assistant-page__floating-chat.is-empty {
  justify-content: center;
}

.assistant-page__viewport {
  flex: 1 1 auto;
  overflow-y: auto;
  scrollbar-gutter: stable;
  padding: 24px 0 80px; /* bottom padding reserves space for floating composer */
  -webkit-mask-image: linear-gradient(to bottom, transparent, black 40px);
  mask-image: linear-gradient(to bottom, transparent, black 40px);
}

.assistant-page__stream {
  width: min(100% - 48px, 720px);
  margin: 0 auto;
  padding: 0;
  display: grid;
  gap: 22px;
}

.assistant-page__footer {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 8px; /* Offset by scrollbar width to keep composer perfectly centered with scrollable messages stream */
  padding: 0 0 2px;
  display: flex;
  flex-direction: column;
  align-items: center;
  pointer-events: none; /* allow scroll-through on empty areas */
  z-index: 20;
}

.assistant-page__floating-chat.is-empty .assistant-page__footer {
  top: 50%;
  bottom: auto;
  right: 0; /* No scrollbar when empty, so reset right offset */
  transform: translateY(-50%);
  padding-top: 0;
  padding-bottom: 0;
}

.assistant-page__jump {
  position: absolute;
  left: 50%;
  /* 
    Footer padding-top is 24px. 
    We want the bottom of the button to be 36px (1.5 lines) above the composer.
    Distance from footer top to composer top = 24px.
    So button bottom should be 12px above footer top.
    Button height is 34px. Top = -12px - 34px = -46px.
  */
  top: -46px;
  transform: translateX(-50%);
  width: 34px;
  height: 34px;
  border-radius: 50%;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-strong) 85%, transparent);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  color: var(--text);
  display: grid;
  place-items: center;
  cursor: pointer;
  z-index: 100;
  pointer-events: auto;

  /* Elastic transitions for smooth, responsive feedback */
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1),
              background-color 0.25s ease,
              border-color 0.25s ease,
              box-shadow 0.25s ease,
              color 0.25s ease;
}

.assistant-page__jump:hover {
  background: color-mix(in srgb, var(--surface-strong) 95%, transparent);
  border-color: var(--primary);
  color: var(--primary);
  /* Elegant float up & slight scale out */
  transform: translateX(-50%) translateY(-3px) scale(1.08);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.15);
}

.assistant-page__jump:active {
  /* Dynamic tactile compression on press */
  transform: translateX(-50%) translateY(1px) scale(0.92);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
  /* Instant response on click release/press */
  transition: transform 0.08s ease, box-shadow 0.08s ease;
}

.assistant-page__hero {
  text-align: center;
  margin-bottom: 32px;
}

.assistant-page__hero h2 {
  font-size: 1.8rem;
  font-weight: 600;
  color: var(--text);
  margin: 0;
  letter-spacing: 0.02em;
}

.assistant-page__composer {
  width: min(100% - 48px, 720px);
  pointer-events: auto; /* re-enable interaction on the bubble itself */
  background: transparent;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  border: 0;
  border-radius: 0;
  padding: 0;
  box-shadow: none;
}

.assistant-page__typing {
  padding: 12px 24px;
  color: var(--muted);
  font-size: 0.88rem;
  font-style: italic;
}

@media (max-width: 720px) {
  .assistant-page__footer {
    padding: 16px 14px 24px;
  }

  .assistant-page__floating-chat.is-empty .assistant-page__footer {
    padding-top: 0;
    padding-bottom: 0;
  }
}
</style>
