import { ref } from 'vue';

const globalActiveStreamController = ref(null);
const globalSending = ref(false);

export function useAssistantStreaming() {
  return {
    activeStreamController: globalActiveStreamController,
    sending: globalSending,
  };
}
