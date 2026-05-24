import { ref, computed, nextTick } from 'vue';
import { shouldAutoScrollToLatest } from '@/lib/assistant.js';

export function useChatScroll(messagesRef) {
  const scrollRef = ref(null);
  const stickToBottom = ref(true);
  const isJumping = ref(false);

  const showJumpToLatest = computed(() => !stickToBottom.value && messagesRef.value.length > 0);

  function readScrollMetrics() {
    const element = scrollRef.value;
    if (!element) {
      return null;
    }

    return {
      scrollTop: element.scrollTop,
      scrollHeight: element.scrollHeight,
      clientHeight: element.clientHeight,
    };
  }

  function handleScroll() {
    if (isJumping.value) {
      stickToBottom.value = true;
      return;
    }
    const metrics = readScrollMetrics();
    if (!metrics) {
      return;
    }

    stickToBottom.value = shouldAutoScrollToLatest(metrics);
  }

  async function scrollToLatest({ behavior = 'auto' } = {}) {
    await nextTick();
    const element = scrollRef.value;
    if (!element) {
      return;
    }

    element.scrollTo({
      top: element.scrollHeight,
      behavior,
    });
    stickToBottom.value = true;
  }

  async function jumpToLatest() {
    isJumping.value = true;
    stickToBottom.value = true;
    await scrollToLatest({ behavior: 'smooth' });
    setTimeout(async () => {
      await scrollToLatest({ behavior: 'auto' });
      isJumping.value = false;
    }, 400);
  }

  return {
    scrollRef,
    stickToBottom,
    isJumping,
    showJumpToLatest,
    handleScroll,
    scrollToLatest,
    jumpToLatest
  };
}
