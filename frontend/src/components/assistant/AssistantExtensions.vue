<template>
  <div class="assistant-message__extensions">
    <div v-if="assistantSuggestions.length" class="assistant-message__section">
      <div class="assistant-message__section-title">推荐追问</div>
      <div class="assistant-message__chips">
        <span v-for="item in assistantSuggestions" :key="item.key" class="assistant-message__chip assistant-message__chip--suggestion" :title="item.prompt">
          {{ item.label }}
        </span>
      </div>
    </div>
    
    <div v-if="assistantNextSteps.length" class="assistant-message__section">
      <div class="assistant-message__section-title">下一步</div>
      <div class="assistant-message__chips">
        <span v-for="step in assistantNextSteps" :key="step" class="assistant-message__chip assistant-message__chip--step">
          {{ step }}
        </span>
      </div>
    </div>
    
    <div v-if="showClarificationCard" class="assistant-message__section assistant-message__clarification">
      <div class="assistant-message__section-title">需要补充的信息</div>
      <p v-if="assistantClarificationCard.question" class="assistant-message__clarification-question">
        {{ assistantClarificationCard.question }}
      </p>
      <div v-if="assistantClarificationCard.options.length" class="assistant-message__chips">
        <span
          v-for="option in assistantClarificationCard.options"
          :key="option.key"
          class="assistant-message__chip assistant-message__chip--clarification"
          :title="option.description || option.value || option.label"
        >
          {{ option.label }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { normalizeAssistantNextSteps, normalizeAssistantSuggestions, normalizeClarificationCard } from '@/lib/assistant.js';

const props = defineProps({
  message: {
    type: Object,
    required: true
  },
  role: {
    type: String,
    required: true
  }
});

const assistantSuggestions = computed(() => normalizeAssistantSuggestions(props.message.suggestions || []));
const assistantNextSteps = computed(() => normalizeAssistantNextSteps(props.message.nextSteps || []));
const assistantClarificationCard = computed(() => normalizeClarificationCard(props.message.clarificationCard || {}));

const showClarificationCard = computed(() => {
  return props.role === 'system'
    && props.message.eventType === 'clarification_card'
    && (Boolean(assistantClarificationCard.value.question) || assistantClarificationCard.value.options.length > 0);
});
</script>

<style scoped>
.assistant-message__section {
  margin-top: 1.5rem;
}
.assistant-message__section-title {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-soft);
  margin-bottom: 0.75rem;
}
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
  background-color: var(--surface-muted);
  color: var(--text-soft);
  border: 1px solid var(--line);
}
.assistant-message__chip:hover {
  background-color: var(--surface-hover);
}
.assistant-message__clarification-question {
  margin-bottom: 0.75rem;
  font-size: 0.875rem;
  color: var(--text-soft);
}
</style>
