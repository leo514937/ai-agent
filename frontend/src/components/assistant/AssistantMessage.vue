<template>
  <article :class="['assistant-message', `assistant-message--${role}`]">
    <div v-if="role === 'system'" class="assistant-message__system">
      <span>{{ message.content }}</span>
      <div v-if="showApprovalActions" class="assistant-message__approval">
        <button
          class="assistant-message__feedback-button"
          type="button"
          :disabled="approvalSubmitting"
          @click="submitApproval('approved')"
        >
          确认继续
        </button>
        <button
          class="assistant-message__feedback-button"
          type="button"
          :disabled="approvalSubmitting"
          @click="submitApproval('rejected')"
        >
          先不执行
        </button>
        <span v-if="approvalHint" class="assistant-message__feedback-hint">{{ approvalHint }}</span>
      </div>
    </div>

    <div v-else-if="role === 'user'" class="assistant-message__user">
      <div class="assistant-message__user-body">
        <div class="assistant-message__user-bubble">
          <p class="assistant-message__content">{{ message.content }}</p>
        </div>
        <div class="assistant-message__actions assistant-message__actions--user">
          <button
            class="assistant-message__action-btn"
            type="button"
            @click="copyText(message.content)"
          >
            <svg v-if="copiedText !== message.content" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
            </svg>
            <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
          </button>
        </div>
      </div>
    </div>

    <div v-else class="assistant-message__assistant">
      <div v-if="assistantMetaLabel" class="assistant-message__meta" :class="{ 'is-fallback': message.fallback }">
        {{ assistantMetaLabel }}
      </div>
      
      <AssistantThinkingBlock
        v-if="hasThinkingBlock"
        :is-thinking-active-raw="isThinkingActiveRaw"
        :is-message-active="message.streaming || isTyping"
        :timeline-steps="timelineSteps"
        :thinking-content="parsedMessage.thinkingContent"
        :message="message"
      />

      <div class="assistant-message__assistant-body">
        <div v-if="parsedMessage.answerContent" class="assistant-message__assistant-bubble">
          <AssistantMarkdown :content="parsedMessage.answerContent" class="assistant-message__markdown" />
          <AssistantCitations :citation-lines="citationLines" />
          <AssistantExtensions :message="message" :role="role" />
          <AssistantCards :message="message" />
        </div>
        
        <div v-if="parsedMessage.answerContent" class="assistant-message__actions assistant-message__actions--assistant">
          <button
            class="assistant-message__action-btn"
            type="button"
            @click="copyText(parsedMessage.answerContent)"
          >
            <svg v-if="copiedText !== parsedMessage.answerContent" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
            </svg>
            <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
          </button>
        </div>
      </div>
    </div>
  </article>
</template>

<script setup>
import { computed, ref } from 'vue';
import AssistantMarkdown from '@/components/assistant/AssistantMarkdown.vue';
import AssistantThinkingBlock from '@/components/assistant/AssistantThinkingBlock.vue';
import AssistantCitations from '@/components/assistant/AssistantCitations.vue';
import AssistantExtensions from '@/components/assistant/AssistantExtensions.vue';
import AssistantCards from '@/components/assistant/AssistantCards.vue';
import { useTypewriter } from '@/composables/useTypewriter.js';
import { useAssistantParsing } from '@/composables/useAssistantParsing.js';

const props = defineProps({
  message: {
    type: Object,
    required: true,
  },
});
const emit = defineEmits(['approval', 'typewrite']);

const role = computed(() => props.message.role || 'assistant');
const messageRef = computed(() => props.message);

const approvalSubmitting = ref(false);
const approvalHint = ref('');

const { displayedRawContent, isTyping } = useTypewriter(messageRef, () => emit('typewrite'));

const { 
  isThinkingActiveRaw,
  parsedMessage,
  timelineSteps,
  hasThinkingBlock,
  citationLines 
} = useAssistantParsing(messageRef, displayedRawContent, isTyping);

const assistantMetaLabel = computed(() => {
  if (role.value !== 'assistant') {
    return '';
  }

  const labels = [];

  if (props.message.source === 'local-business-compat') {
    labels.push(props.message.fallback ? '已降级为本地业务回答' : '本地业务回答');
  } else if (props.message.source === 'learning-agent-service') {
    labels.push(props.message.fallback ? '知识增强回答（降级）' : '知识增强回答');
  } else if (props.message.fallback) {
    labels.push('已降级回答');
  }

  if (props.message.cancelled) {
    labels.push('已停止生成');
  }

  if (!labels.length && props.message.cancelled) {
    return '已停止生成';
  }

  return labels.join(' · ');
});

const showApprovalActions = computed(() => {
  return role.value === 'system'
    && props.message.eventType === 'approval_required'
    && Boolean(props.message.sessionId && props.message.turnId);
});

const copiedText = ref('');
function copyText(text) {
  if (!text) return;
  navigator.clipboard.writeText(text).then(() => {
    copiedText.value = text;
    setTimeout(() => {
      if (copiedText.value === text) copiedText.value = '';
    }, 2000);
  });
}

function submitApproval(status) {
  if (!props.message.sessionId || !props.message.turnId) {
    return;
  }
  approvalSubmitting.value = true;
  approvalHint.value = '提交中...';
  
  emit('approval', {
    sessionId: props.message.sessionId,
    turnId: props.message.turnId,
    status,
    message: props.message,
    onSuccess() {
      approvalSubmitting.value = false;
      approvalHint.value = '已提交。';
      setTimeout(() => {
        approvalHint.value = '';
      }, 3000);
    },
    onError() {
      approvalSubmitting.value = false;
      approvalHint.value = '提交失败，请重试。';
    }
  });
}
</script>

<style scoped>
.assistant-message {
  margin-bottom: 2rem;
  max-width: 720px;
  width: 100%;
}

/* User Message Styles */
.assistant-message--user {
  margin-left: auto;
  display: flex;
  justify-content: flex-end;
}
.assistant-message__user {
  width: 100%;
  display: flex;
  justify-content: flex-end;
}
.assistant-message__user-body {
  max-width: 66.67%; /* Exactly 2/3 of AI reply's max-width (100%) */
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.5rem;
}
.assistant-message__user-bubble {
  background-color: var(--surface-muted);
  padding: 1rem 1.25rem;
  border-radius: 1.5rem;
  color: var(--text);
  font-size: 1rem;
  line-height: 1.5;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}
.assistant-message__content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}

/* Assistant Message Styles */
.assistant-message--assistant {
  margin-right: auto;
  width: 100%;
}
.assistant-message__assistant {
  max-width: 100%;
  width: 100%;
}
.assistant-message__assistant-body {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.5rem;
  width: 100%;
  margin-top: 0.75rem;
}
.assistant-message__assistant-bubble {
  background-color: transparent;
  border: none;
  padding: 0;
  border-radius: 0;
  color: var(--text);
  font-size: 1rem;
  line-height: 1.6;
  box-shadow: none;
  width: 100%;
}
/* Meta info (time, status) */
.assistant-message__meta {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.75rem;
  color: var(--muted);
  background-color: var(--surface-muted);
  padding: 0.125rem 0.5rem;
  border-radius: 1rem;
}
.assistant-message__meta.is-fallback {
  color: var(--amber);
  background-color: rgba(245, 158, 11, 0.1);
}

/* Action Buttons (Copy, Refresh) */
.assistant-message__actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.5rem;
}
.assistant-message__action-btn {
  background: transparent;
  border: none;
  padding: 0.25rem;
  cursor: pointer;
  color: var(--muted);
  border-radius: 0.25rem;
  transition: all 0.2s;
}
.assistant-message__action-btn:hover {
  background-color: var(--surface-muted);
  color: var(--text-soft);
}

/* System Messages */
.assistant-message--system .assistant-message__system {
  display: inline-block;
  font-size: 0.875rem;
  color: var(--amber);
  background-color: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.2);
  padding: 0.5rem 1rem;
  border-radius: 0.5rem;
  margin: 0 auto;
}
.assistant-message__approval {
  margin-top: 0.75rem;
  display: flex;
  gap: 0.5rem;
  justify-content: center;
  align-items: center;
}
.assistant-message__feedback-button {
  background-color: #fff;
  border: 1px solid #fcd34d;
  padding: 0.375rem 1rem;
  border-radius: 9999px;
  font-size: 0.875rem;
  color: #b45309;
  cursor: pointer;
  transition: all 0.2s;
  font-weight: 500;
}
.assistant-message__feedback-button:hover:not(:disabled) {
  background-color: #fef3c7;
}
.assistant-message__feedback-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.assistant-message__feedback-hint {
  font-size: 0.75rem;
  color: #b45309;
  margin-left: 0.5rem;
}

/* Cards & Sections */
.assistant-message__section {
  margin-top: 1.5rem;
}
.assistant-message__section-title {
  font-size: 0.875rem;
  font-weight: 600;
  color: #374151;
  margin-bottom: 0.75rem;
}
.assistant-message__cards {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.assistant-message__generic-card {
  border: 1px solid #e5e7eb;
  border-radius: 0.5rem;
  padding: 1rem;
  background-color: #fff;
}
.assistant-message__generic-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}
.assistant-message__generic-card-badge {
  background-color: #f3f4f6;
  color: #4b5563;
  padding: 0.125rem 0.5rem;
  border-radius: 1rem;
  font-size: 0.75rem;
}
.assistant-message__generic-card-copy {
  margin: 0;
  font-size: 0.875rem;
  color: #6b7280;
}

/* Chips */
.assistant-message__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.assistant-message__chip {
  padding: 0.375rem 0.875rem;
  border-radius: 1rem;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.2s;
  background-color: #f3f4f6;
  color: #374151;
  border: 1px solid #e5e7eb;
}
.assistant-message__chip:hover {
  background-color: #e5e7eb;
}

/* Markdown adjustments */
.assistant-message__markdown {
  font-size: 1rem;
  line-height: 1.6;
  color: var(--text);
}

/* Transitions */
.collapse-enter-active,
.collapse-leave-active {
  transition: max-height 0.3s ease-out, opacity 0.3s ease-out, margin 0.3s ease-out;
  overflow: hidden;
  max-height: 2000px; /* 大胆的值 */
}

.collapse-enter-from,
.collapse-leave-to {
  max-height: 0;
  opacity: 0;
  margin-top: 0;
  margin-bottom: 0;
}

</style>
