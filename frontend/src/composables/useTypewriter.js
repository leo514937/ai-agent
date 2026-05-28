import { computed, ref, watch, onBeforeUnmount } from 'vue';
import { normalizeAssistantMessage } from '@/lib/assistant.js';

export function useTypewriter(messageRef, emitTypewrite) {
  const displayedRawContent = ref('');
  const isTyping = ref(false);
  let typewriterTimer = null;
  let targetText = '';
  let finishing = false; // accelerated catch-up mode after streaming ends
  const normalizedMessage = computed(() => normalizeAssistantMessage(messageRef.value));

  function startTypewriter() {
    if (typewriterTimer) return;

    const tick = () => {
      const currentLen = displayedRawContent.value.length;
      const targetLen = targetText.length;

      if (currentLen >= targetLen) {
        typewriterTimer = null;
        finishing = false;
        isTyping.value = false;
        return;
      }

      const remaining = targetLen - currentLen;
      let charsToAppend = 1;

      if (finishing) {
        // Accelerated finish: type fast but still visually animate
        if (remaining > 200) {
          charsToAppend = Math.ceil(remaining / 6);
        } else if (remaining > 80) {
          charsToAppend = Math.ceil(remaining / 5);
        } else if (remaining > 30) {
          charsToAppend = 6;
        } else if (remaining > 10) {
          charsToAppend = 3;
        } else {
          charsToAppend = 2;
        }
      } else {
        if (remaining > 30) {
          charsToAppend = Math.ceil(remaining / 8);
        } else if (remaining > 15) {
          charsToAppend = 3;
        } else if (remaining > 5) {
          charsToAppend = 2;
        } else {
          charsToAppend = 1;
        }
      }

      displayedRawContent.value += targetText.substring(currentLen, currentLen + charsToAppend);
      emitTypewrite();
    };

    const run = () => {
      tick();
      if (displayedRawContent.value.length < targetText.length) {
        const remaining = targetText.length - displayedRawContent.value.length;
        let delay;
        
        if (finishing) {
          // Faster intervals during catch-up
          delay = remaining > 80 ? 4 : remaining > 30 ? 8 : 12;
        } else {
          delay = 35;
          if (remaining > 30) {
            delay = 8;
          } else if (remaining > 15) {
            delay = 15;
          } else if (remaining > 5) {
            delay = 25;
          }
        }
        
        typewriterTimer = setTimeout(run, delay);
      } else {
        typewriterTimer = null;
        finishing = false;
        isTyping.value = false;
      }
    };

    isTyping.value = true;
    run();
  }

  watch(
    () => normalizedMessage.value.answerContent,
    (newContent) => {
      const contentStr = newContent || '';

      if (!messageRef.value.streaming && !typewriterTimer) {
        // No active typewriter and not streaming — set content immediately
        // (e.g. loading historical messages from storage)
        displayedRawContent.value = contentStr;
        targetText = contentStr;
        return;
      }
      
      targetText = contentStr;
      
      if (!typewriterTimer && targetText.length > displayedRawContent.value.length) {
        startTypewriter();
      }
    },
    { immediate: true }
  );

  watch(
    () => messageRef.value.streaming,
    (isStreaming) => {
      if (!isStreaming) {
        // Streaming ended — update target text but let typewriter finish gracefully
        targetText = normalizedMessage.value.answerContent || '';
        
        if (typewriterTimer) {
          // Typewriter is running — switch to accelerated catch-up mode
          finishing = true;
        } else if (displayedRawContent.value !== targetText) {
          // Typewriter not running but content differs — start accelerated typewriter
          finishing = true;
          startTypewriter();
        }
        // If content already fully displayed, do nothing
      }
    }
  );

  onBeforeUnmount(() => {
    if (typewriterTimer) {
      clearTimeout(typewriterTimer);
      typewriterTimer = null;
      isTyping.value = false;
    }
  });

  return {
    displayedRawContent,
    isTyping
  };
}
