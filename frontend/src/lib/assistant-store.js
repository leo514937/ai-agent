import { mockAssistantSessions } from './mock-data.js';
import { normalizeAssistantMessage } from './assistant.js';
import { readStoredJSON, writeStoredJSON } from './storage.js';

const SESSIONS_KEY = 'hmdp-ai-sessions';
const ACTIVE_KEY = 'hmdp-ai-active-session';
export const ASSISTANT_STATE_EVENT = 'hmdp-assistant-state-changed';

function cloneSession(session) {
  return {
    ...session,
    context: { ...(session.context || {}) },
    messages: Array.isArray(session.messages)
      ? session.messages.map((message) => (message?.role === 'assistant'
        ? normalizeAssistantMessage({ ...message })
        : { ...message }))
      : [],
  };
}

export function createAssistantSessionId() {
  return `sess-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function createAssistantSession({ title = '新对话', page = 'assistant', context = {}, seedMessage = '' } = {}) {
  const now = new Date().toISOString();
  const session = {
    id: createAssistantSessionId(),
    title,
    page,
    topic: context.typeName || context.shopName || context.blogTitle || '',
    createdAt: now,
    updatedAt: now,
    context: { ...context },
    messages: [],
  };

  if (seedMessage) {
    session.messages.push({
      id: `${session.id}-seed`,
      role: 'user',
      content: seedMessage,
      createdAt: now,
    });
  }

  return session;
}

export function notifyAssistantStateChange() {
  if (typeof window === 'undefined' || typeof window.dispatchEvent !== 'function') {
    return;
  }

  window.dispatchEvent(new Event(ASSISTANT_STATE_EVENT));
}

export function loadAssistantSessions(storage = typeof window !== 'undefined' ? window.localStorage : undefined) {
  const stored = readStoredJSON(storage, SESSIONS_KEY, null);
  if (Array.isArray(stored) && stored.length > 0) {
    return stored.map(cloneSession);
  }

  return mockAssistantSessions.map(cloneSession);
}

export function saveAssistantSessions(storage, sessions, { notify = true } = {}) {
  writeStoredJSON(storage, SESSIONS_KEY, sessions.map(cloneSession));
  if (notify) {
    notifyAssistantStateChange();
  }
}

export function loadActiveSessionId(storage = typeof window !== 'undefined' ? window.localStorage : undefined) {
  return readStoredJSON(storage, ACTIVE_KEY, '') || '';
}

export function saveActiveSessionId(storage, sessionId, { notify = true } = {}) {
  writeStoredJSON(storage, ACTIVE_KEY, sessionId || '');
  if (notify) {
    notifyAssistantStateChange();
  }
}

export function appendSessionMessage(session, message) {
  const next = cloneSession(session);
  const now = new Date().toISOString();
  const nextMessage = {
    id: `${session.id}-${next.messages.length + 1}`,
    createdAt: now,
    ...message,
  };
  next.messages.push(nextMessage.role === 'assistant' ? normalizeAssistantMessage(nextMessage) : nextMessage);
  next.updatedAt = now;
  if (message.role === 'user' && (!next.title || next.title === '新对话')) {
    const content = String(message.content || '').trim();
    const shortTitle = content.slice(0, 4);
    next.title = content.length > 4 ? `${shortTitle}...` : shortTitle || '新对话';
  }
  return next;
}

export function updateSessionMessage(session, messageId, updates) {
  const next = cloneSession(session);
  const index = next.messages.findIndex((message) => message.id === messageId);
  if (index === -1) {
    return next;
  }

  const current = next.messages[index];
  const patch = typeof updates === 'function' ? updates({ ...current }) : (updates || {});
  next.messages[index] = {
    ...current,
    ...patch,
  };
  if (next.messages[index].role === 'assistant') {
    next.messages[index] = normalizeAssistantMessage(next.messages[index]);
  }
  next.updatedAt = new Date().toISOString();
  return next;
}

export function upsertSession(sessions, session) {
  const index = sessions.findIndex((item) => item.id === session.id);
  if (index === -1) {
    return [cloneSession(session), ...sessions];
  }

  const next = sessions.slice();
  next[index] = cloneSession(session);
  return next;
}
