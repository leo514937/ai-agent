import { requestEventStream, requestJson } from './http.js';
import {
  buildAssistantSessionMessage,
  buildAssistantTimelineEntry,
  buildAssistantSystemMessage,
  normalizeAssistantEnvelope,
  normalizeAssistantResponse,
} from './assistant.js';
import {
  getMockShopById,
  getMockBlogById,
  mockAssistantSessions,
  mockBlogs,
  mockMeStats,
  mockUserProfile,
} from './mock-data.js';
import { buildShopTags, formatDistance, formatPrice, formatScore, normalizeShopImages, pickShopCover } from './shops.js';

const TYPE_SUMMARY_BY_ID = {
  1: '吃喝美食',
  2: '聚会夜宵',
  3: '休闲轻食',
  4: '甜品拍照',
  5: '清爽日料',
  6: '本帮风味',
  7: '亲子出游',
  8: '喝酒小聚',
  9: '运动放松',
  10: '医美护理',
};

let cachedShopTypes = null;
let cachedShops = null;

function enrichShop(shop) {
  const type = cachedShopTypes?.find((item) => Number(item.id) === Number(shop.typeId));
  const typeName = shop.typeName || type?.name || '店铺';
  const icon = type?.icon || typeName?.[0] || '店';
  return {
    ...shop,
    cover: pickShopCover(shop),
    imageList: normalizeShopImages(shop.images),
    scoreText: formatScore(shop.score),
    distanceText: formatDistance(shop.distance),
    priceText: formatPrice(shop.avgPrice),
    metaText: [shop.area, shop.openHours].filter(Boolean).join(' · '),
    tags: shop.tags?.length ? shop.tags : buildShopTags(shop, typeName),
    typeName,
    typeIcon: icon && String(icon).includes('/') ? (typeName?.[0] || '店') : icon,
  };
}

function enrichShopType(type) {
  const id = Number(type?.id);
  const name = String(type?.name || '').trim();
  return {
    ...type,
    id,
    name,
    icon: String(type?.icon || '').trim(),
    summary: TYPE_SUMMARY_BY_ID[id] || (name ? `${name} 分类` : '分类'),
  };
}

async function requestJsonOrEmpty(path, options = {}) {
  try {
    const data = await requestJson(path, options);
    return data ?? [];
  } catch {
    return [];
  }
}

function enrichBlog(blog) {
  const shop = blog.shopId ? getMockShopById(blog.shopId) : null;
  return {
    ...blog,
    cover: normalizeShopImages(blog.images)[0] || '',
    authorLabel: blog.name || '本地生活助手',
    likeText: `${blog.liked || 0}`,
    commentText: `${blog.comments || 0}`,
    metaText: shop ? `${shop.area} · ${shop.name}` : blog.summary || '',
    tags: [shop?.area, shop?.name, blog.summary].filter(Boolean).slice(0, 3),
  };
}

function enrichVoucher(voucher) {
  return {
    ...voucher,
    payText: `¥${voucher.payValue}`,
    actualText: `¥${voucher.actualValue}`,
    stockText: voucher.stock > 0 ? `剩余 ${voucher.stock}` : '已抢空',
    timeText: [voucher.beginTime, voucher.endTime].filter(Boolean).join(' - '),
  };
}

function fallbackIfEmpty(result, fallback) {
  if (Array.isArray(result) && result.length) {
    return result;
  }

  return fallback;
}

async function requestJsonOrFallback(path, fallback, options = {}) {
  try {
    const data = await requestJson(path, options);
    if (Array.isArray(data)) {
      return fallbackIfEmpty(data, fallback);
    }
    return data || fallback;
  } catch {
    return fallback;
  }
}

export async function loadShopTypes() {
  if (Array.isArray(cachedShopTypes)) {
    return cachedShopTypes;
  }

  const data = await requestJsonOrEmpty('/shop-type/list');
  cachedShopTypes = Array.isArray(data) ? data.map(enrichShopType) : [];
  return cachedShopTypes;
}

async function loadBackendShops() {
  if (Array.isArray(cachedShops)) {
    return cachedShops;
  }

  const types = await loadShopTypes();
  const pages = await Promise.all(
    types.map(async (type) => {
      const data = await requestJsonOrEmpty(`/shop/of/type?typeId=${encodeURIComponent(type.id)}&current=1`);
      return Array.isArray(data) ? data : [];
    }),
  );

  const seen = new Set();
  const merged = [];
  for (const page of pages) {
    for (const item of page) {
      const shopId = Number(item?.id);
      if (!Number.isFinite(shopId) || seen.has(shopId)) {
        continue;
      }
      seen.add(shopId);
      merged.push(enrichShop(item));
    }
  }

  cachedShops = merged;
  return cachedShops;
}

export async function loadShopsPage({ typeId = 'all', query = '' } = {}) {
  const typeValue = String(typeId || 'all');
  const allShops = await loadBackendShops();
  const data = typeValue === 'all'
    ? allShops
    : allShops.filter((shop) => String(shop.typeId) === typeValue);

  const normalizedQuery = String(query || '').trim().toLowerCase();
  const filtered = normalizedQuery
    ? data.filter((shop) => [shop.name, shop.area, shop.address, ...(shop.tags || [])].join(' ').toLowerCase().includes(normalizedQuery))
    : data;
  return filtered;
}

export async function loadShopDetail(id) {
  const shopId = Number(id);
  const data = await requestJsonOrEmpty(`/shop/${shopId}`);
  if (!data || typeof data !== 'object' || Array.isArray(data) || !data.id) {
    return null;
  }
  return enrichShop(data);
}

export async function loadShopVouchers(shopId) {
  const id = Number(shopId);
  const data = await requestJsonOrEmpty(`/voucher/list/${id}`);
  const vouchers = Array.isArray(data) ? data : [];
  return vouchers.map(enrichVoucher);
}

export async function loadHotBlogs() {
  const data = await requestJsonOrFallback('/blog/hot?current=1', mockBlogs);
  const list = Array.isArray(data) ? data : mockBlogs;
  return list.map(enrichBlog);
}

export async function loadBlogFeed() {
  const data = await requestJsonOrFallback('/blog/of/follow?lastId=999999999999', mockBlogs.slice(0, 3));
  const list = Array.isArray(data) ? data : mockBlogs.slice(0, 3);
  return list.map(enrichBlog);
}

export async function loadBlogDetail(id) {
  const blogId = Number(id);
  const data = await requestJsonOrFallback(`/blog/${blogId}`, getMockBlogById(blogId));
  return data ? enrichBlog(data) : enrichBlog(getMockBlogById(blogId) || mockBlogs[0]);
}

export async function loadBlogLikes(id) {
  try {
    const data = await requestJson(`/blog/likes/${Number(id)}`);
    return Array.isArray(data) ? data : [];
  } catch {
    return [
      { id: 1, nickName: '小探', icon: 'T' },
      { id: 2, nickName: '口碑官', icon: 'K' },
      { id: 3, nickName: '火锅控', icon: 'H' },
    ];
  }
}

export async function loadUserSummary() {
  const remote = await requestJsonOrFallback('/user/me', mockUserProfile);
  return remote || mockUserProfile;
}

export async function loadUserInfo(userId) {
  const remote = await requestJsonOrFallback(`/user/info/${Number(userId)}`, null);
  return remote || null;
}

export async function loadSignCount() {
  const remote = await requestJsonOrFallback('/user/sign/count', mockMeStats.signStreak);
  return typeof remote === 'number' ? remote : mockMeStats.signStreak;
}

export async function recordSignIn() {
  try {
    await requestJson('/user/sign', { method: 'POST' });
    return { source: 'remote', success: true };
  } catch {
    return { source: 'local', success: true };
  }
}

export async function sendAssistantPrompt(payload) {
  const result = await streamAssistantPrompt(payload);
  return normalizeAssistantResponse(
    result.final?.finalPayload
      || result.final
      || result.terminalMessage?.clarificationCard
      || result.terminalMessage?.payload
      || {},
  );
}

function buildFallbackFinalMessage(timeline, meta, payload) {
  const normalizedPayload = payload && typeof payload === 'object' && !Array.isArray(payload)
    ? payload
    : {};
  const candidate = buildAssistantSessionMessage(normalizedPayload, {
    ...meta,
    eventTimeline: Array.isArray(timeline) ? timeline.slice() : [],
    finalPayload: normalizedPayload,
  });

  const content = String(candidate?.answerContent || candidate?.answer || candidate?.content || '').trim();
  if (!content) {
    return null;
  }

  return candidate;
}

function extractLastAnswerLikePayload(timeline) {
  const entries = Array.isArray(timeline) ? timeline.slice().reverse() : [];
  for (const entry of entries) {
    const payload = entry && typeof entry.payload === 'object' && !Array.isArray(entry.payload)
      ? entry.payload
      : {};
    const answerLike = payload.answer_text
      || payload.answer
      || payload.content
      || payload.delta
      || payload.summary
      || payload.message;
    if (String(answerLike || '').trim()) {
      return payload;
    }
  }
  return null;
}

const ASSISTANT_STREAM_EVENTS = new Set([
  'ack',
  'heartbeat',
  'load_context_started',
  'load_context_done',
  'intent_analysis_started',
  'intent_analysis_done',
  'query_rewrite_started',
  'query_rewrite_done',
  'retrieval_started',
  'embedding_started',
  'embedding_done',
  'qdrant_search_started',
  'qdrant_search_done',
  'rrf_fusion_started',
  'rrf_fusion_done',
  'rerank_started',
  'rerank_done',
  'answer_stream_started',
  'delta',
  'answer_delta',
  'clarification_card',
  'retrieval_result',
  'memory_retrieval_started',
  'memory_retrieval_result',
  'memory_promotion_result',
  'tool_call',
  'tool_result',
  'plan_execution_started',
  'plan_step_result',
  'approval_required',
  'plan_replanned',
  'plan_execution_summary',
  'final',
  'error',
]);

function updateStreamMeta(target, source = {}) {
  if (source.traceId) {
    target.traceId = source.traceId;
  }
  if (source.turnId) {
    target.turnId = source.turnId;
  }
  if (source.sessionId) {
    target.sessionId = source.sessionId;
  }
}

export async function streamAssistantPrompt(payload, handlers = {}, options = {}) {
  const timeline = [];
  const meta = {
    traceId: '',
    turnId: '',
    sessionId: String(payload?.sessionId || ''),
  };
  const userSignal = options?.signal;
  let finalMessage = null;
  let terminalType = '';
  let terminalMessage = null;
  let errorMessage = null;
  let lastAnswerPayload = null;

  // Internal AbortController: wraps the user's signal and also aborts
  // automatically when a terminal event (final/error) is received.
  // This prevents readEventStream from hanging when the TCP connection
  // does not close promptly after the backend finishes streaming.
  const internalController = new AbortController();
  const internalSignal = internalController.signal;

  // Forward the user's abort to our internal controller.
  let userAbortForwarder;
  if (userSignal) {
    if (userSignal.aborted) {
      internalController.abort();
    } else {
      userAbortForwarder = () => internalController.abort();
      userSignal.addEventListener('abort', userAbortForwarder, { once: true });
    }
  }

  // Track whether we aborted internally (after receiving final/error)
  // so we can distinguish from a user-triggered abort.
  let selfAborted = false;

  try {
    await requestEventStream('/ai/chat/stream', {
      method: 'POST',
      body: payload,
      signal: internalSignal,
      async onEvent(rawEvent) {
        if (userSignal?.aborted) {
          return;
        }
        const normalized = normalizeAssistantEnvelope(rawEvent);
        if (!ASSISTANT_STREAM_EVENTS.has(normalized.type)) {
          return;
        }

        updateStreamMeta(meta, normalized);
        const entry = buildAssistantTimelineEntry(rawEvent, meta);
        timeline.push(entry);
        await handlers.onEvent?.(entry);

        if (entry.type === 'final') {
          finalMessage = buildAssistantSessionMessage(normalized.payload, {
            ...meta,
            eventTimeline: timeline.slice(),
            finalPayload: normalized.payload,
          });
          await handlers.onFinal?.(finalMessage, entry);
          // Terminal event received — force-stop stream reading.
          selfAborted = true;
          internalController.abort();
          return;
        }

        if (entry.type === 'delta' || entry.type === 'answer_delta') {
          lastAnswerPayload = normalized.payload;
          await handlers.onDelta?.(entry);
          return;
        }

        if (entry.type === 'clarification_card') {
          terminalType = 'clarification_card';
          terminalMessage = buildAssistantSystemMessage(entry);
          await handlers.onProgress?.(terminalMessage, entry);
          // Terminal event received — force-stop stream reading.
          selfAborted = true;
          internalController.abort();
          return;
        }

        if (entry.type === 'error') {
          errorMessage = buildAssistantSystemMessage(entry);
          await handlers.onError?.(errorMessage, entry);
          // Terminal event received — force-stop stream reading.
          selfAborted = true;
          internalController.abort();
          return;
        }

        if (entry.type === 'ack') {
          await handlers.onAck?.(entry);
          return;
        }

        await handlers.onProgress?.(buildAssistantSystemMessage(entry), entry);
      },
    });
  } catch (error) {
    // User manually cancelled.
    if (userSignal?.aborted || (!selfAborted && error?.name === 'AbortError')) {
      return {
        final: null,
        error: null,
        cancelled: true,
        terminalType: 'cancelled',
        terminalMessage: null,
        timeline,
        meta,
      };
    }
    // Internal self-abort after receiving a terminal event — not an error,
    // just fall through to the normal return logic below.
    if (selfAborted && error?.name === 'AbortError') {
      // Expected — we aborted the stream ourselves after final/error/clarification.
    } else {
      throw error;
    }
  } finally {
    if (userSignal && userAbortForwarder) {
      userSignal.removeEventListener('abort', userAbortForwarder);
    }
  }

  if (userSignal?.aborted) {
    return {
      final: null,
      error: null,
      cancelled: true,
      terminalType: 'cancelled',
      terminalMessage: null,
      timeline,
      meta,
    };
  }

  if (errorMessage) {
    return {
      final: null,
      error: errorMessage,
      terminalType,
      terminalMessage,
      timeline,
      meta,
    };
  }

  if (terminalType === 'clarification_card' && terminalMessage) {
    return {
      final: null,
      error: null,
      terminalType,
      terminalMessage,
      timeline,
      meta,
    };
  }

  if (!finalMessage) {
    if (!finalMessage && lastAnswerPayload) {
      finalMessage = buildFallbackFinalMessage(timeline, meta, lastAnswerPayload);
    }
    if (!finalMessage) {
      const timelinePayload = extractLastAnswerLikePayload(timeline);
      if (timelinePayload) {
        finalMessage = buildFallbackFinalMessage(timeline, meta, timelinePayload);
      }
    }
    if (!finalMessage && timeline.length > 0) {
      finalMessage = buildFallbackFinalMessage(timeline, meta, {
        answer_text: '抱歉，这次回答没有完整返回 final 结果，请稍后重试。',
        source: 'local-life-agent',
        mode: 'stream',
      });
    }
    if (finalMessage) {
      return {
        final: finalMessage,
        error: null,
        terminalType: 'final',
        terminalMessage: finalMessage,
        timeline,
        meta,
      };
    }
    throw new Error('AI 返回中缺少 final 结果');
  }

  return {
    final: finalMessage,
    error: null,
    terminalType: 'final',
    terminalMessage: finalMessage,
    timeline,
    meta,
  };
}

export async function submitAssistantApproval(payload) {
  return requestJson('/ai/approval/submit', {
    method: 'POST',
    body: payload,
  });
}

export async function submitAssistantFeedback(payload) {
  return requestJson('/ai/feedback/report', {
    method: 'POST',
    body: payload,
  });
}

export async function loadHomeSnapshot() {
  const [types, blogs, featuredShops] = await Promise.all([
    loadShopTypes(),
    loadHotBlogs(),
    loadShopsPage({ typeId: 'all', query: '' }),
  ]);
  return {
    types: Array.isArray(types) ? types : [],
    blogs: Array.isArray(blogs) ? blogs : mockBlogs,
    featuredShops: Array.isArray(featuredShops) ? featuredShops.slice(0, 4) : [],
  };
}

export function seedAssistantSessions() {
  return mockAssistantSessions.map((session) => ({
    ...session,
    messages: session.messages.map((message) => ({ ...message })),
  }));
}
