<template>
  <div class="assistant-history">
    <div class="assistant-history__list">
      <button
        v-for="session in sessions"
        :key="session.id"
        :class="['assistant-history__item', session.id === activeId && 'assistant-history__item--active']"
        type="button"
        @click="$emit('select', session.id)"
      >
        <span class="assistant-history__item-title">{{ session.title || '新对话' }}</span>
        <span class="assistant-history__item-actions">
          <span class="assistant-history__item-time">{{ formatTime(session.updatedAt) }}</span>
          <span
            class="assistant-history__delete"
            @click.stop="$emit('delete', session.id)"
            title="删除会话"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </span>
        </span>
      </button>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  sessions: {
    type: Array,
    default: () => [],
  },
  activeId: {
    type: String,
    default: '',
  },
});

const emit = defineEmits(['select', 'delete']);

function formatTime(value) {
  if (!value) {
    return '';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }

  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  }

  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
}
</script>

<style scoped>
.assistant-history {
  display: grid;
  gap: 10px;
}

.assistant-history__list {
  display: grid;
  gap: 8px;
}

.assistant-history__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  background: transparent;
  border: 1px solid transparent;
  text-align: left;
  color: inherit;
  cursor: pointer;
  transition: all 0.2s ease;
}

.assistant-history__item:hover {
  background: var(--surface-hover);
}

.assistant-history__item--active {
  background: var(--surface-muted);
}

.assistant-history__item-title {
  font-weight: 600;
  font-size: 0.9rem;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}

.assistant-history__item-actions {
  display: flex;
  align-items: center;
  flex: none;
}

.assistant-history__item-time {
  color: var(--muted);
  font-size: 0.75rem;
  white-space: nowrap;
}

.assistant-history__delete {
  display: none;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  place-items: center;
  color: var(--muted);
  transition: all 0.2s ease;
}

.assistant-history__delete:hover {
  background: var(--surface-strong);
  color: var(--text);
}

.assistant-history__item:hover .assistant-history__item-time {
  display: none;
}

.assistant-history__item:hover .assistant-history__delete {
  display: grid;
}
</style>
