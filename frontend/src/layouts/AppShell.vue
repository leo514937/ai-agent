<template>
  <div class="app-shell">
    <div class="app-shell__glow app-shell__glow--left" />
    <div class="app-shell__glow app-shell__glow--right" />

    <div class="app-shell__frame">
      <AppHeader
        :subtitle="pageSubtitle"
        :theme="theme"
        :backend-status="backendStatus"
        @toggle-theme="toggleTheme"
        @search="handleSearch"
      />

      <div class="layout">
        <aside class="sidebar">
          <div class="sidebar__nav panel">
            <AppNav :items="navItems" />
          </div>

          <div class="sidebar__assistant panel">
            <div class="assistant-head">
              <p class="eyebrow">AI Assistant</p>
              <button class="btn btn-primary btn-sm" @click="handleNewChat">
                + 新对话
              </button>
            </div>
            <div class="assistant-body">
              <AssistantHistory
                :sessions="sessions"
                :active-id="activeSessionId"
                @select="handleSessionSelect"
                @delete="handleSessionDelete"
              />
            </div>
          </div>
        </aside>

        <main class="main">
          <slot />
        </main>
      </div>
    </div>

    <div class="dock panel mobile-only">
      <AppNav :items="navItems" compact @navigate="scrollToTop" />
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import AppHeader from '@/components/AppHeader.vue';
import AppNav from '@/components/AppNav.vue';
import AssistantHistory from '@/components/assistant/AssistantHistory.vue';
import {
  ASSISTANT_STATE_EVENT,
  loadActiveSessionId,
  loadAssistantSessions,
  notifyAssistantStateChange,
  saveActiveSessionId,
  saveAssistantSessions,
  createAssistantSession,
  upsertSession,
} from '@/lib/assistant-store.js';
import { buildNavItems, resolveRouteSubtitle, resolveRouteTitle } from '@/lib/navigation.js';
import { requestJson } from '@/lib/http.js';
import { readStoredValue, writeStoredValue } from '@/lib/storage.js';

const router = useRouter();
const route = useRoute();
const themeKey = 'hmdp-theme';
const backendStatus = ref({ kind: 'offline', label: '本地演示' });
const theme = ref('light');

const navItems = computed(() => buildNavItems());
const pageTitle = computed(() => route.meta?.title || resolveRouteTitle(route.path));
const pageSubtitle = computed(() => route.meta?.subtitle || resolveRouteSubtitle(route.path));

const sessions = ref(loadAssistantSessions());
const activeSessionId = ref(loadActiveSessionId() || '');

function syncAssistantStateFromStorage() {
  sessions.value = loadAssistantSessions(window.localStorage);
  activeSessionId.value = loadActiveSessionId(window.localStorage);
}

function handleNewChat() {
  const session = createAssistantSession({ title: '新对话', page: 'assistant' });
  sessions.value = upsertSession(sessions.value, session);
  activeSessionId.value = session.id;
  saveAssistantSessions(window.localStorage, sessions.value, { notify: false });
  saveActiveSessionId(window.localStorage, session.id, { notify: false });
  router.push({ path: '/ai', query: { id: session.id } });
  notifyAssistantStateChange();
}

function handleSessionSelect(sessionId) {
  activeSessionId.value = sessionId;
  saveActiveSessionId(window.localStorage, sessionId, { notify: false });
  router.push({ path: '/ai', query: { id: sessionId } });
  notifyAssistantStateChange();
}

function handleSessionDelete(sessionId) {
  const index = sessions.value.findIndex((s) => s.id === sessionId);
  if (index !== -1) {
    sessions.value.splice(index, 1);
    saveAssistantSessions(window.localStorage, sessions.value, { notify: false });
    if (activeSessionId.value === sessionId) {
      activeSessionId.value = sessions.value[0]?.id || '';
      saveActiveSessionId(window.localStorage, activeSessionId.value, { notify: false });
    }
    notifyAssistantStateChange();
  }
}

// Watch for route changes to sync activeSessionId if needed
watch(
  () => route.query.id,
  (newId) => {
    if (newId) {
      activeSessionId.value = String(newId);
    }
  },
);

function applyTheme(value) {
  document.documentElement.dataset.theme = value;
  writeStoredValue(window.localStorage, themeKey, value);
}

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark';
}

function handleSearch(keyword) {
  const query = String(keyword || '').trim();
  if (!query) {
    return;
  }

  router.push({ path: '/shops', query: { q: query } });
}

function scrollToTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

watch(theme, (value) => applyTheme(value));

onMounted(async () => {
  theme.value = readStoredValue(window.localStorage, themeKey, 'light');
  applyTheme(theme.value);

  try {
    await requestJson('/shop-type/list');
    backendStatus.value = { kind: 'online', label: 'API 在线' };
  } catch {
    backendStatus.value = { kind: 'offline', label: '本地演示' };
  }
});

function handleAssistantStateChange() {
  syncAssistantStateFromStorage();
}

onMounted(() => {
  syncAssistantStateFromStorage();
  window.addEventListener(ASSISTANT_STATE_EVENT, handleAssistantStateChange);
});

onBeforeUnmount(() => {
  window.removeEventListener(ASSISTANT_STATE_EVENT, handleAssistantStateChange);
});
</script>

<style scoped>
.sidebar__assistant {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px;
  margin-top: 16px;
}

.assistant-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.assistant-head .eyebrow {
  margin: 0;
  font-size: 0.72rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  font-weight: 800;
}

.assistant-body {
  margin: 0 -4px;
  padding: 0 4px;
}

:deep(.assistant-history__item) {
  padding: 10px;
  border-radius: 12px;
}
</style>
