<template>
  <div class="assistant-message__thinking-block">
    <button
      class="assistant-message__thinking-toggle-btn"
      type="button"
      @click="showThinkingDetail = !showThinkingDetail"
    >
      <span class="thinking-label" :class="{ 'is-thinking': isThinkingActiveRaw }">
        {{ isThinkingActiveRaw ? '思考中 ' + displayTime : '已思考 ' + displayTime }}
      </span>
      <span style="color: red; font-weight: bold; margin-left: 10px;">[DEBUG: BLOCK IS MOUNTED!]</span>
      <svg
        class="toggle-arrow"
        :class="{ 'is-expanded': showThinkingDetail }"
        width="10"
        height="10"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="3"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <polyline points="9 18 15 12 9 6" />
      </svg>
    </button>

    <transition name="collapse">
      <div v-show="showThinkingDetail && (timelineSteps.length > 0 || thinkingContent)" class="assistant-message__thinking-content-wrapper">
        <div v-if="timelineSteps.length" class="assistant-message__timeline-list">
          <div v-for="(step, index) in timelineSteps" :key="index" class="assistant-message__timeline-item">
            {{ step }}
          </div>
        </div>
        <div v-if="thinkingContent" class="assistant-message__thinking-text">
          {{ thinkingContent }}
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, watch, computed, onBeforeUnmount } from 'vue';

const props = defineProps({
  isThinkingActiveRaw: {
    type: Boolean,
    default: false
  },
  isMessageActive: {
    type: Boolean,
    default: false
  },
  timelineSteps: {
    type: Array,
    default: () => []
  },
  thinkingContent: {
    type: String,
    default: ''
  },
  message: {
    type: Object,
    default: () => ({})
  }
});

const showThinkingDetail = ref(props.isMessageActive || props.isThinkingActiveRaw);

watch(() => props.isMessageActive, (newVal) => {
  showThinkingDetail.value = newVal;
});

const thinkingTime = ref(0);
let timerId = null;

const calculateStaticDuration = () => {
  const timeline = props.message?.eventTimeline || [];
  if (!timeline || timeline.length === 0) {
    return 0;
  }
  const startTime = new Date(timeline[0].createdAt || timeline[0].timestamp).getTime();
  
  let endTime = null;
  for (const entry of timeline) {
    if (['delta', 'answer_delta', 'final', 'answer_stream_started'].includes(entry.type)) {
      endTime = new Date(entry.createdAt || entry.timestamp).getTime();
      break;
    }
  }
  
  if (!endTime) {
    endTime = new Date(timeline[timeline.length - 1].createdAt || timeline[timeline.length - 1].timestamp).getTime();
  }
  
  const diff = Math.max(1, Math.round((endTime - startTime) / 1000));
  return isNaN(diff) ? 0 : diff;
};

const updateLiveTimer = () => {
  const timeline = props.message?.eventTimeline || [];
  if (!timeline || timeline.length === 0) {
    thinkingTime.value = 0;
    return;
  }
  const startTime = new Date(timeline[0].createdAt || timeline[0].timestamp).getTime();
  const now = Date.now();
  const elapsed = Math.max(1, Math.round((now - startTime) / 1000));
  thinkingTime.value = isNaN(elapsed) ? 0 : elapsed;
};

const startTimer = () => {
  stopTimer();
  updateLiveTimer();
  timerId = setInterval(updateLiveTimer, 1000);
};

const stopTimer = () => {
  if (timerId) {
    clearInterval(timerId);
    timerId = null;
  }
};

watch(() => props.isThinkingActiveRaw, (isActive, wasActive) => {
  if (isActive) {
    startTimer();
  } else {
    stopTimer();
    // Lock the live timer value so the displayed time never jumps backward.
    // Only fall back to calculateStaticDuration if the live timer never started.
    if (!thinkingTime.value || thinkingTime.value <= 0) {
      thinkingTime.value = calculateStaticDuration();
    }
    // else: keep thinkingTime.value as-is (the last live reading)
  }
}, { immediate: true });

watch(() => props.message?.eventTimeline?.length, () => {
  if (props.isThinkingActiveRaw) {
    updateLiveTimer();
  } else {
    thinkingTime.value = calculateStaticDuration();
  }
});

onBeforeUnmount(() => {
  stopTimer();
});

const displayTime = computed(() => {
  let timeVal = thinkingTime.value;
  if (!timeVal || timeVal <= 0) {
    timeVal = calculateStaticDuration();
  }
  if (!timeVal || timeVal <= 0) {
    if (props.thinkingContent) {
      timeVal = Math.max(2, Math.min(15, Math.round(props.thinkingContent.length / 40)));
    } else {
      timeVal = 3;
    }
  }
  return `${timeVal}s`;
});
</script>

<style scoped>
.assistant-message__thinking-block {
  margin-bottom: 0.75rem;
}

.assistant-message__thinking-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  background: transparent;
  border: none;
  padding: 0;
  cursor: pointer;
  color: var(--muted);
  font-size: 0.875rem;
  font-family: inherit;
  transition: opacity 0.2s;
  user-select: none;
}

.assistant-message__thinking-toggle-btn:hover {
  opacity: 0.8;
}

.thinking-label {
  display: inline-flex;
  align-items: center;
}

.thinking-label.is-thinking {
  background: linear-gradient(
    90deg,
    var(--muted) 0%,
    var(--text-soft) 25%,
    var(--text) 50%,
    var(--text-soft) 75%,
    var(--muted) 100%
  );
  background-size: 200% auto;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  animation: textShimmer 2s infinite linear;
  font-weight: 500;
}

.toggle-arrow {
  color: var(--muted);
  transition: transform 0.2s ease;
}

.toggle-arrow.is-expanded {
  transform: rotate(90deg);
}

.assistant-message__thinking-content-wrapper {
  margin-top: 0.5rem;
  padding: 0.75rem 1rem;
  background-color: var(--surface-muted);
  border-left: 3px solid var(--line);
  border-radius: 0.5rem;
  font-size: 0.875rem;
  color: var(--muted); /* 灰色小字 */
  line-height: 1.6;
}

.assistant-message__timeline-list {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  margin-bottom: 0.5rem;
}

.assistant-message__timeline-item {
  position: relative;
  padding-left: 1rem;
}

.assistant-message__timeline-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0.45rem;
  width: 0.375rem;
  height: 0.375rem;
  background-color: var(--muted);
  border-radius: 50%;
}

.assistant-message__thinking-text {
  white-space: pre-wrap;
  word-break: break-word;
}

@keyframes textShimmer {
  0% {
    background-position: -200% 0;
  }
  100% {
    background-position: 200% 0;
  }
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
