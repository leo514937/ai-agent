import { ref, computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  createAssistantSession,
  loadActiveSessionId,
  loadAssistantSessions,
  notifyAssistantStateChange,
  saveActiveSessionId,
  saveAssistantSessions,
  upsertSession,
} from '@/lib/assistant-store.js';

export function useChatSession() {
  const route = useRoute();
  const router = useRouter();

  const sessions = ref([]);
  const activeSessionId = ref('');

  const currentSession = computed(() => {
    return sessions.value.find((session) => session.id === activeSessionId.value) || null;
  });

  function pickValidSessionId(list, candidates = []) {
    const ids = new Set(list.map((session) => session.id));
    for (const candidate of candidates) {
      if (candidate && ids.has(candidate)) {
        return candidate;
      }
    }
    return list[0]?.id || '';
  }

  function syncRoute(sessionId) {
    const nextId = sessionId || '';
    const currentId = String(route.query.id || '');

    if (currentId === nextId) {
      return;
    }

    router.replace({
      path: '/ai',
      query: nextId ? { id: nextId } : {},
    });
  }

  function loadSessionsFromStorage() {
    const nextSessions = loadAssistantSessions(window.localStorage);

    if (!nextSessions.length) {
      const session = createAssistantSession({ title: '新对话', page: 'ai' });
      sessions.value = [session];
      activeSessionId.value = session.id;
      saveAssistantSessions(window.localStorage, sessions.value, { notify: false });
      saveActiveSessionId(window.localStorage, session.id, { notify: false });
      syncRoute(session.id);
      notifyAssistantStateChange();
      return;
    }

    sessions.value = nextSessions;
    const routeId = String(route.query.id || '');
    const storedId = loadActiveSessionId(window.localStorage);
    const nextActiveId = pickValidSessionId(nextSessions, [routeId, storedId, activeSessionId.value]);
    activeSessionId.value = nextActiveId;

    if (nextActiveId) {
      syncRoute(nextActiveId);
    }
  }

  function persistSession(session, { notify = true } = {}) {
    sessions.value = upsertSession(sessions.value, session);
    saveAssistantSessions(window.localStorage, sessions.value, { notify: false });
    if (notify) {
      notifyAssistantStateChange();
    }
  }

  async function ensureCurrentSession() {
    if (currentSession.value) {
      return currentSession.value;
    }

    const session = createAssistantSession({ title: '新对话', page: 'ai' });
    persistSession(session, { notify: false });
    activeSessionId.value = session.id;
    saveActiveSessionId(window.localStorage, session.id, { notify: false });
    syncRoute(session.id);
    notifyAssistantStateChange();
    return session;
  }

  return {
    sessions,
    activeSessionId,
    currentSession,
    loadSessionsFromStorage,
    persistSession,
    ensureCurrentSession,
    syncRoute
  };
}
