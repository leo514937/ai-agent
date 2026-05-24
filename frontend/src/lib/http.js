import { readStoredValue } from './storage.js';

const DEFAULT_API_BASE = '/api';
const TOKEN_KEY = 'hmdp-token';

export function joinApiUrl(basePath, path) {
  const cleanPath = String(path || '').replace(/^\/+/, '');
  const normalizedBase = String(basePath || '').trim();

  if (!normalizedBase) {
    return `/${cleanPath}`.replace(/\/+$/, '');
  }

  if (/^https?:\/\//i.test(normalizedBase)) {
    return `${normalizedBase.replace(/\/+$/, '')}/${cleanPath}`;
  }

  const base = normalizedBase.replace(/^\/+|\/+$/g, '');
  const joined = [base, cleanPath].filter(Boolean).join('/');
  return `/${joined}`.replace(/\/+/g, '/');
}

export function unwrapResult(payload) {
  if (!payload || payload.success !== true) {
    throw new Error(payload?.errorMsg || '请求失败');
  }

  return payload.data;
}

function resolveAuthToken(storage) {
  return readStoredValue(storage, TOKEN_KEY, '');
}

function resolveStorage(storage) {
  return storage ?? (typeof window !== 'undefined' ? window.localStorage : undefined);
}

function buildRequestHeaders({
  headers = {},
  token,
  storage,
  accept = 'application/json',
}) {
  const requestHeaders = {
    Accept: accept,
    ...headers,
  };

  const authToken = token !== undefined ? token : resolveAuthToken(resolveStorage(storage));
  if (authToken) {
    requestHeaders.authorization = authToken;
  }

  return requestHeaders;
}

function shouldAttachJsonBody(method, body) {
  return body !== undefined && body !== null && method !== 'GET' && method !== 'HEAD';
}

async function readResponseText(response) {
  if (typeof response.text === 'function') {
    return response.text();
  }

  const chunks = [];
  await readEventStream(response.body, (event) => {
    if (typeof event.data === 'string') {
      chunks.push(event.data);
    }
  });
  return chunks.join('\n');
}

function readSseBlock(block) {
  const lines = String(block || '').split(/\r?\n/);
  let type = 'message';
  const dataLines = [];

  for (const line of lines) {
    if (!line || line.startsWith(':')) {
      continue;
    }

    const separatorIndex = line.indexOf(':');
    const field = separatorIndex === -1 ? line : line.slice(0, separatorIndex);
    const rawValue = separatorIndex === -1 ? '' : line.slice(separatorIndex + 1);
    const value = rawValue.startsWith(' ') ? rawValue.slice(1) : rawValue;

    if (field === 'event') {
      type = value || 'message';
      continue;
    }

    if (field === 'data') {
      dataLines.push(value);
    }
  }

  if (!dataLines.length && type === 'message') {
    return null;
  }

  const rawData = dataLines.join('\n');
  let data = rawData;
  if (rawData) {
    try {
      data = JSON.parse(rawData);
    } catch {
      data = rawData;
    }
  }

  return {
    type,
    data,
  };
}

function findSseBoundary(buffer) {
  const crlfIndex = buffer.indexOf('\r\n\r\n');
  const lfIndex = buffer.indexOf('\n\n');

  if (crlfIndex === -1 && lfIndex === -1) {
    return null;
  }

  if (crlfIndex === -1) {
    return { index: lfIndex, length: 2 };
  }

  if (lfIndex === -1 || crlfIndex < lfIndex) {
    return { index: crlfIndex, length: 4 };
  }

  return { index: lfIndex, length: 2 };
}

export async function readEventStream(stream, onEvent, { signal } = {}) {
  if (!stream || typeof stream.getReader !== 'function') {
    return;
  }

  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const safeCancelReader = async () => {
    try {
      await reader.cancel();
    } catch {
      // stream 在 abort/error 竞争态下可能已关闭或抛出 AbortError，这里吞掉即可
    }
  };

  // If the signal is already aborted before we start, cancel immediately.
  if (signal?.aborted) {
    await safeCancelReader();
    return;
  }

  // Register a listener so that if the signal fires mid-read, we cancel the
  // underlying reader. This causes the pending reader.read() to resolve with
  // { done: true }, breaking us out of the loop.
  let abortHandler;
  if (signal) {
    abortHandler = () => {
      void safeCancelReader();
    };
    signal.addEventListener('abort', abortHandler, { once: true });
  }

  try {
    while (true) {
      if (signal?.aborted) {
        await safeCancelReader();
        break;
      }

      let done = false;
      let value;
      try {
        ({ done, value } = await reader.read());
      } catch (error) {
        if (signal?.aborted || error?.name === 'AbortError') {
          break;
        }
        throw error;
      }
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

      while (true) {
        const boundary = findSseBoundary(buffer);
        if (!boundary) {
          break;
        }

        const block = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary.length);
        const event = readSseBlock(block);
        if (event) {
          await onEvent(event);
        }
      }

      if (done) {
        break;
      }
    }

    if (!signal?.aborted) {
      const trailingEvent = readSseBlock(buffer.trim());
      if (trailingEvent) {
        await onEvent(trailingEvent);
      }
    }
  } finally {
    if (signal && abortHandler) {
      signal.removeEventListener('abort', abortHandler);
    }
  }
}

export async function requestJson(path, options = {}) {
  const {
    method = 'GET',
    body,
    headers = {},
    token,
    storage,
    basePath = DEFAULT_API_BASE,
    signal,
  } = options;

  const requestHeaders = buildRequestHeaders({
    headers,
    token,
    storage,
    accept: 'application/json',
  });

  if (shouldAttachJsonBody(method, body)) {
    requestHeaders['Content-Type'] = requestHeaders['Content-Type'] || 'application/json';
  }

  const response = await fetch(joinApiUrl(basePath, path), {
    method,
    headers: requestHeaders,
    signal,
    body: shouldAttachJsonBody(method, body)
      ? JSON.stringify(body)
      : undefined,
  });

  const rawText = await response.text();
  const payload = rawText ? JSON.parse(rawText) : null;

  if (!response.ok) {
    throw new Error(payload?.errorMsg || `请求失败(${response.status})`);
  }

  return unwrapResult(payload);
}

export async function requestEventStream(path, options = {}) {
  const {
    method = 'POST',
    body,
    headers = {},
    token,
    storage,
    basePath = DEFAULT_API_BASE,
    signal,
    onEvent = () => {},
  } = options;

  const requestHeaders = buildRequestHeaders({
    headers,
    token,
    storage,
    accept: 'text/event-stream',
  });

  if (shouldAttachJsonBody(method, body)) {
    requestHeaders['Content-Type'] = requestHeaders['Content-Type'] || 'application/json';
  }

  const response = await fetch(joinApiUrl(basePath, path), {
    method,
    headers: requestHeaders,
    signal,
    body: shouldAttachJsonBody(method, body)
      ? JSON.stringify(body)
      : undefined,
  });

  if (!response.ok) {
    const rawText = await readResponseText(response);
    let payload = null;
    if (rawText) {
      try {
        payload = JSON.parse(rawText);
      } catch {
        payload = null;
      }
    }
    throw new Error(payload?.errorMsg || `请求失败(${response.status})`);
  }

  await readEventStream(response.body, onEvent, { signal });
}
