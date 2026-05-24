import { computed } from 'vue';
import { formatAssistantTimelineEntry, normalizeAssistantMessage } from '@/lib/assistant.js';

export function useAssistantParsing(messageRef, displayedRawContentRef) {
  const normalizedMessage = computed(() => normalizeAssistantMessage(messageRef.value));

  const isThinkingActiveRaw = computed(() => {
    if (normalizedMessage.value.cancelled) {
      return false;
    }

    return Boolean(messageRef.value.streaming)
      && Boolean(normalizedMessage.value.thinkingContent || !parsedMessage.value.answerContent);
  });

  const isThinkingActiveTypewriter = computed(() => {
    if (normalizedMessage.value.cancelled) {
      return false;
    }
    return Boolean(messageRef.value.streaming)
      && Boolean(normalizedMessage.value.thinkingContent || !parsedMessage.value.answerContent);
  });

  const parsedMessage = computed(() => {
    return {
      hasThinking: Boolean(normalizedMessage.value.thinkingContent || timelineSteps.value.length),
      thinkingContent: normalizedMessage.value.thinkingContent || '',
      answerContent: displayedRawContentRef.value || normalizedMessage.value.answerContent || '',
    };
  });

  const timelineSteps = computed(() => {
    if (!messageRef.value.eventTimeline) return [];
    const steps = [];
    const ignoreTypes = new Set(['approval_required', 'clarification_card', 'error', 'final', 'ack', 'delta', 'answer_delta']);
    
    for (const entry of messageRef.value.eventTimeline) {
      if (ignoreTypes.has(entry.type)) {
        continue;
      }
      const text = formatAssistantTimelineEntry(entry);
      if (text && text !== '处理中。' && text !== '正在生成回答。') {
        steps.push(text);
      }
    }
    return steps.filter((step, i, arr) => i === 0 || step !== arr[i - 1]);
  });

  const hasThinkingBlock = computed(() => {
    return parsedMessage.value.hasThinking || timelineSteps.value.length > 0;
  });

  const citationLines = computed(() => {
    const citations = Array.isArray(messageRef.value.citations) ? messageRef.value.citations : [];
    return citations
      .map((item, index) => {
        if (!item || typeof item !== 'object') {
          return `引用 ${index + 1}`;
        }
        const sourceType = item.source_type || item.sourceType;
        const title = item.title || item.document_id || item.documentId || item.chunk_id || item.chunkId || `引用 ${index + 1}`;
        const locator = item.locator || item.snippet || '';
        return [sourceType, title, locator].filter(Boolean).join(' · ');
      })
      .filter(Boolean);
  });

  return {
    isThinkingActiveRaw,
    isThinkingActiveTypewriter,
    parsedMessage,
    timelineSteps,
    hasThinkingBlock,
    citationLines
  };
}
