<template>
  <form class="assistant-composer" @submit.prevent="submit">
    <div class="assistant-composer__shell">
      <textarea
        ref="textareaRef"
        v-model="draft"
        class="assistant-composer__textarea"
        :placeholder="placeholder"
        :disabled="loading"
        rows="1"
        @keydown="handleKeyDown"
      />
      <div class="assistant-composer__actions">
        <button
          v-if="streaming || loading"
          class="assistant-composer__btn assistant-composer__btn--stop"
          type="button"
          aria-label="停止生成"
          @click="$emit('stop')"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <rect x="5" y="5" width="14" height="14" rx="2" />
          </svg>
        </button>
        <button
          v-else
          class="assistant-composer__btn assistant-composer__btn--send"
          type="submit"
          :disabled="!draft.trim()"
          aria-label="发送消息"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="19" x2="12" y2="5"></line>
            <polyline points="5 12 12 5 19 12"></polyline>
          </svg>
        </button>
      </div>
    </div>
    <div v-if="suggestions.length" class="assistant-composer__suggestions">
      <button
        v-for="item in suggestions"
        :key="item.key || item.prompt || item.label"
        class="chip"
        type="button"
        @click="$emit('pick', item.prompt)"
      >
        <span v-if="item.icon" class="chip__icon" v-html="item.icon"></span>
        {{ item.label }}
      </button>
    </div>
    
    <p v-if="hint" class="assistant-composer__hint">{{ hint }}</p>
  </form>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue';

const props = defineProps({
  modelValue: {
    type: String,
    default: '',
  },
  placeholder: {
    type: String,
    default: '有问必答...',
  },
  loading: {
    type: Boolean,
    default: false,
  },
  streaming: {
    type: Boolean,
    default: false,
  },
  suggestions: {
    type: Array,
    default: () => [],
  },
});

const emit = defineEmits(['update:modelValue', 'submit', 'pick', 'stop']);

const draft = ref(props.modelValue);
const textareaRef = ref(null);

watch(
  () => props.modelValue,
  async (value) => {
    if (value !== draft.value) {
      draft.value = value;
    }
    await nextTick();
    adjustHeight();
  },
);

watch(draft, async (value) => {
  emit('update:modelValue', value);
  await nextTick();
  adjustHeight();
});

function adjustHeight() {
  const textarea = textareaRef.value;
  if (!textarea) {
    return;
  }

  textarea.style.height = 'auto';
  textarea.style.height = `${textarea.scrollHeight}px`;
}

function submit() {
  const content = draft.value.trim();
  if (!content || props.loading) {
    return;
  }

  emit('submit', content);
}

function handleKeyDown(event) {
  if (event.key === 'Enter' && !event.shiftKey && !props.loading) {
    event.preventDefault();
    submit();
  }
}
</script>

<style scoped>
.assistant-composer {
  padding: 0;
  background: transparent;
  box-shadow: none;
  border: 0;
  display: flex;
  flex-direction: column;
}

.assistant-composer__suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
  justify-content: center;
}

.assistant-composer__shell {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  padding: 8px 12px 8px 16px;
  border-radius: 26px;
  background: var(--surface-strong);
  border: 1px solid var(--line);
  box-shadow: 0 12px 24px rgba(0, 0, 0, 0.06);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.assistant-composer__shell:focus-within {
  border-color: var(--primary-strong);
  box-shadow: 0 12px 24px rgba(0, 0, 0, 0.08), 0 0 0 2px var(--primary-soft);
}

.assistant-composer__textarea {
  flex: 1;
  min-height: 24px;
  max-height: 60vh;
  padding: 6px 0;
  margin: 0;
  resize: none;
  border: 0;
  outline: none;
  background: transparent;
  color: var(--text);
  font-size: 1rem;
  line-height: 1.5;
  font-family: inherit;
}

.assistant-composer__textarea::placeholder {
  color: var(--muted);
  opacity: 0.6;
}

/* For WebKit scrollbars inside the textarea */
.assistant-composer__textarea::-webkit-scrollbar {
  width: 6px;
}
.assistant-composer__textarea::-webkit-scrollbar-thumb {
  background: var(--line);
  border-radius: 4px;
}

.assistant-composer__actions {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 2px;
}

.assistant-composer__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 50%;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  flex-shrink: 0;
  outline: none;
}

.assistant-composer__btn--send {
  background: linear-gradient(145deg, var(--primary, #06b6d4), var(--primary-strong, #0891b2));
  color: var(--surface-strong, #ffffff);
}

.assistant-composer__btn--send:hover:not(:disabled) {
  transform: scale(1.08);
  filter: brightness(1.1);
}

.assistant-composer__btn--send:active:not(:disabled) {
  transform: scale(0.92);
}

.assistant-composer__btn--send:disabled {
  background: var(--line, #e2e8f0);
  color: var(--muted, #94a3b8);
  opacity: 0.45;
  cursor: not-allowed;
}

.assistant-composer__btn--stop {
  background: #ef4444;
  color: #ffffff;
  box-shadow: 0 0 12px rgba(239, 68, 68, 0.35);
}

.assistant-composer__btn--stop:hover {
  transform: scale(1.08);
  background: #dc2626;
  box-shadow: 0 0 16px rgba(239, 68, 68, 0.5);
}

.assistant-composer__btn--stop:active {
  transform: scale(0.92);
}

.assistant-composer__hint {
  margin: 8px 0 0;
  color: var(--muted);
  font-size: 0.75rem;
  text-align: center;
  opacity: 0.8;
}

@media (max-width: 720px) {
  .assistant-composer__shell {
    padding: 6px 10px 6px 14px;
  }
}
</style>
