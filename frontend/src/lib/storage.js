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
    storage.setItem(key, next);
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
