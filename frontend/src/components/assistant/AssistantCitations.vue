<template>
  <div v-if="citationLines.length" class="assistant-message__section assistant-message__section--citations">
    <button
      class="assistant-message__citations-toggle-btn"
      type="button"
      @click="showCitations = !showCitations"
    >
      <svg
        class="toggle-icon-book"
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
        <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
      </svg>
      <span>{{ showCitations ? '收起依据' : '展开依据 (' + citationLines.length + ')' }}</span>
      <svg
        class="toggle-icon"
        :class="{ 'is-expanded': showCitations }"
        width="12"
        height="12"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2.5"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <polyline points="6 9 12 15 18 9" />
      </svg>
    </button>

    <transition name="collapse">
      <div v-if="showCitations" class="assistant-message__citation-container">
        <ul class="assistant-message__citation-list">
          <li v-for="line in citationLines" :key="line" class="assistant-message__citation-item">
            {{ line }}
          </li>
        </ul>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref } from 'vue';

defineProps({
  citationLines: {
    type: Array,
    default: () => []
  }
});

const showCitations = ref(false);
</script>

<style scoped>
.assistant-message__section--citations {
  margin-top: 1rem;
}

.assistant-message__citations-toggle-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: transparent;
  border: none;
  padding: 0;
  cursor: pointer;
  color: #6b7280;
  font-size: 0.875rem;
  font-weight: 500;
  transition: opacity 0.2s;
}

.assistant-message__citations-toggle-btn:hover {
  opacity: 0.8;
}

.toggle-icon-book {
  color: #9ca3af;
}

.toggle-icon {
  color: #9ca3af;
  transition: transform 0.3s ease;
}

.toggle-icon.is-expanded {
  transform: rotate(180deg);
}

.assistant-message__citation-container {
  margin-top: 0.5rem;
  background-color: var(--surface-muted);
  border: 1px solid var(--line);
  border-radius: 0.5rem;
  padding: 0.75rem 1rem;
}

.assistant-message__citation-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.assistant-message__citation-item {
  font-size: 0.75rem;
  color: var(--muted);
  line-height: 1.4;
  word-break: break-all;
  position: relative;
  padding-left: 0.75rem;
}

.assistant-message__citation-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0.4rem;
  width: 0.25rem;
  height: 0.25rem;
  background-color: var(--muted);
  border-radius: 50%;
}

.collapse-enter-active,
.collapse-leave-active {
  transition: all 0.3s ease-out;
  overflow: hidden;
  max-height: 2000px; /* arbitrary large value */
}

.collapse-enter-from,
.collapse-leave-to {
  max-height: 0;
  opacity: 0;
  margin-top: 0;
  padding-top: 0;
  padding-bottom: 0;
}
</style>
