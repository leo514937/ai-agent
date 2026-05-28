function isMapStorage(storage) {
  return storage && typeof storage.get === 'function' && typeof storage.set === 'function';
}

function isWebStorage(storage) {
  return storage && typeof storage.getItem === 'function' && typeof storage.setItem === 'function';
}

export function readStoredValue(storage, key, fallback = '') {
  if (!storage) {
    return fallback;
  }

  if (isWebStorage(storage)) {
    const value = storage.getItem(key);
    return value == null || value === '' ? fallback : value;
  }

  if (isMapStorage(storage)) {
    const value = storage.get(key);
    return value == null || value === '' ? fallback : value;
  }

  return fallback;
}

export function writeStoredValue(storage, key, value) {
  if (!storage) {
    return;
  }

  const next = value == null ? '' : String(value);

  if (isWebStorage(storage)) {
    try {
      storage.setItem(key, next);
    } catch (e) {
      if (e.name === 'QuotaExceededError' || e.name === 'NS_ERROR_DOM_QUOTA_REACHED' || e.code === 22) {
        console.warn('LocalStorage quota exceeded for key:', key, 'attempting auto-heal...');
        if (key === 'hmdp-ai-sessions') {
          try {
            const sessions = JSON.parse(next);
            if (Array.isArray(sessions) && sessions.length > 0) {
              // Auto-heal: Keep only the most recent 2 sessions and strip heavy payloads
              const healed = sessions.slice(0, 2).map(session => {
                const messages = (session.messages || []).map(msg => {
                  if (msg.role === 'assistant') {
                    return {
                      id: msg.id,
                      role: msg.role,
                      content: msg.content,
                      createdAt: msg.createdAt,
                      thinkingContent: msg.thinkingContent,
                      hasThinking: msg.hasThinking,
                      shops: (msg.shops || []).map(s => ({ id: s.id, name: s.name })),
                      vouchers: (msg.vouchers || []).map(v => ({ id: v.id, title: v.title })),
                    };
                  }
                  return {
                    id: msg.id,
                    role: msg.role,
                    content: msg.content,
                    createdAt: msg.createdAt,
                  };
                });
                return {
                  ...session,
                  messages,
                };
              });
              storage.setItem(key, JSON.stringify(healed));
              console.log('LocalStorage auto-heal successful. Trimmed down old sessions.');
              return;
            }
          } catch (healError) {
            console.error('Failed to auto-heal localStorage sessions:', healError);
          }
        }
        // Fallback: Clear the key if heal fails
        try {
          storage.removeItem(key);
          console.warn('Cleared localStorage key due to quota limit:', key);
        } catch (rmError) {
          console.error(rmError);
        }
      } else {
        console.error('Failed to set localStorage value:', e);
      }
    }
    return;
  }

  if (isMapStorage(storage)) {
    storage.set(key, next);
  }
}

export function removeStoredValue(storage, key) {
  if (!storage) {
    return;
  }

  if (isWebStorage(storage)) {
    storage.removeItem(key);
    return;
  }

  if (isMapStorage(storage)) {
    storage.delete(key);
  }
}

export function readStoredJSON(storage, key, fallback) {
  const raw = readStoredValue(storage, key, '');
  if (!raw) {
    return fallback;
  }

  try {
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

export function writeStoredJSON(storage, key, value) {
  writeStoredValue(storage, key, JSON.stringify(value));
}
