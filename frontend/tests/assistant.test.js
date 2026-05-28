import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildAssistantSessionMessage,
  buildAssistantMessagePayload,
  formatAssistantTimelineEntry,
  normalizeAssistantResponse,
  normalizeAssistantMessage,
  splitAssistantMessageContent,
  normalizeAssistantSuggestions,
  shouldAutoScrollToLatest,
} from '../src/lib/assistant.js';
import {
  appendSessionMessage,
  createAssistantSession,
  updateSessionMessage,
} from '../src/lib/assistant-store.js';
import { streamAssistantPrompt, submitAssistantApproval, submitAssistantFeedback } from '../src/lib/catalog.js';

test('normalizeAssistantResponse 兼容 final payload 字段并保留数组', () => {
  const response = normalizeAssistantResponse({
    answer_text: 'hello',
    citations: [{ title: '引用A', snippet: '依据摘要' }],
    suggestions: [{ label: '看优惠券', prompt: '看看这家店的优惠券' }],
    shops: [{ id: 1, name: '店铺A' }],
    vouchers: [{ id: 2, title: '券A' }],
    cards: [{ title: '卡片A' }],
    next_steps: ['继续问价格'],
    task_chain: [{ step: 'retrieval' }],
  });

  assert.equal(response.answer, 'hello');
  assert.equal(response.citations.length, 1);
  assert.equal(response.suggestions.length, 1);
  assert.equal(response.suggestions[0].label, '看优惠券');
  assert.equal(response.suggestions[0].prompt, '看看这家店的优惠券');
  assert.equal(response.shops.length, 1);
  assert.equal(response.vouchers.length, 1);
  assert.equal(response.cards.length, 1);
  assert.equal(response.nextSteps.length, 1);
  assert.equal(response.taskChain.length, 1);
});

test('splitAssistantMessageContent 会把思考块和主回答拆开', () => {
  const parts = splitAssistantMessageContent(
    '<details open><summary><b>💭 深度思考中...</b></summary>先梳理需求</details>\n\n最终答案',
  );

  assert.equal(parts.hasThinking, true);
  assert.equal(parts.thinkingContent, '先梳理需求');
  assert.equal(parts.answerContent, '最终答案');
});

test('normalizeAssistantMessage 会把旧的原始内容规范化成稳定字段', () => {
  const message = normalizeAssistantMessage({
    role: 'assistant',
    content: '<details open><summary><b>💭 深度思考中...</b></summary>正在分析</details>\n\n这是主回答',
  });

  assert.equal(message.content, '这是主回答');
  assert.equal(message.answer, '这是主回答');
  assert.equal(message.answerContent, '这是主回答');
  assert.equal(message.thinkingContent, '正在分析');
});

test('normalizeAssistantSuggestions 兼容字符串和对象形式', () => {
  const items = normalizeAssistantSuggestions([
    '看看优惠券',
    { title: '推荐店铺', prompt: '推荐附近店铺', icon: 'A' },
  ]);

  assert.equal(items.length, 2);
  assert.deepEqual(items[0], {
    label: '看看优惠券',
    prompt: '看看优惠券',
    icon: '',
    key: '0-看看优惠券',
  });
  assert.equal(items[1].label, '推荐店铺');
  assert.equal(items[1].prompt, '推荐附近店铺');
  assert.equal(items[1].icon, 'A');
});

test('buildAssistantMessagePayload includes page and context', () => {
  assert.deepEqual(
    buildAssistantMessagePayload('推荐附近火锅', { page: 'shops', shopId: 12 }),
    { message: '推荐附近火锅', page: 'shops', context: { page: 'shops', shopId: 12 } },
  );
});

test('buildAssistantSessionMessage 保留 assistant metadata', () => {
  const message = buildAssistantSessionMessage({
    answer_text: '推荐结果',
    mode: 'recommend',
    source: 'learning-agent-service',
    fallback: false,
    citations: [{ title: '引用A' }],
    shops: [{ id: 1, name: '店铺A' }],
    vouchers: [{ id: 2, title: '券A' }],
    cards: [{ title: '卡片A' }],
    next_steps: ['看详情'],
    task_chain: [{ step: 'search' }],
    context: { page: 'ai' },
  }, {
    traceId: 'trace-1',
    turnId: 'turn-1',
    sessionId: 'sess-1',
    eventTimeline: [{ type: 'retrieval_started' }],
  });

  assert.equal(message.role, 'assistant');
  assert.equal(message.content, '推荐结果');
  assert.equal(message.answer, '推荐结果');
  assert.equal(message.answerContent, '推荐结果');
  assert.equal(message.thinkingContent, '');
  assert.equal(message.source, 'learning-agent-service');
  assert.equal(message.fallback, false);
  assert.equal(message.citations.length, 1);
  assert.equal(message.shops.length, 1);
  assert.equal(message.vouchers.length, 1);
  assert.equal(message.cards.length, 1);
  assert.equal(message.nextSteps[0], '看详情');
  assert.equal(message.taskChain[0].step, 'search');
  assert.equal(message.traceId, 'trace-1');
  assert.equal(message.turnId, 'turn-1');
  assert.equal(message.sessionId, 'sess-1');
  assert.equal(message.eventTimeline.length, 1);
});

test('formatAssistantTimelineEntry 会把 approval_required 渲染成待确认提示', () => {
  const text = formatAssistantTimelineEntry({
    type: 'approval_required',
    payload: {
      reason: '该操作需要你确认后才能继续执行',
    },
  });

  assert.match(text, /待确认/);
  assert.match(text, /需要你确认/);
});

test('streamAssistantPrompt 消费 SSE 并返回 final assistant message', async (t) => {
  const originalFetch = global.fetch;
  const requests = [];
  global.fetch = async (url, options) => {
    requests.push({ url, options });
    return {
      ok: true,
      body: new ReadableStream({
        start(controller) {
          const encoder = new TextEncoder();
          controller.enqueue(encoder.encode('event: ack\n'));
          controller.enqueue(encoder.encode('data: {"traceId":"trace-1","sessionId":"sess-1","turnId":"turn-1","payload":{"message":"accepted"}}\n\n'));
          controller.enqueue(encoder.encode('event: retrieval_started\n'));
          controller.enqueue(encoder.encode('data: {"payload":{"query":"火锅"}}\n\n'));
          controller.enqueue(encoder.encode('event: delta\n'));
          controller.enqueue(encoder.encode('data: {"traceId":"trace-1","sessionId":"sess-1","turnId":"turn-1","payload":{"delta":"最终","answer_text":"最终"}}\n\n'));
          controller.enqueue(encoder.encode('event: final\n'));
          controller.enqueue(encoder.encode('data: {"payload":{"answer_text":"最终答案","source":"learning-agent-service","fallback":false,"citations":[{"title":"引用A","snippet":"依据摘要"}],"suggestions":[{"label":"继续问优惠券","prompt":"继续问优惠券"}],"shops":[{"id":1,"name":"店铺A"}],"vouchers":[{"id":2,"title":"券A"}],"cards":[{"title":"卡片A"}],"task_chain":[{"step":"search"}],"next_steps":["继续问优惠券"],"context":{"page":"ai"}}}\n\n'));
          controller.close();
        },
      }),
    };
  };
  t.after(() => {
    global.fetch = originalFetch;
  });

  const seenEvents = [];
  const seenDeltas = [];
  const result = await streamAssistantPrompt(
    { message: '你好', context: { page: 'ai' } },
    {
      onEvent(event) {
        seenEvents.push(event.type);
      },
      onDelta(entry) {
        seenDeltas.push(entry.payload.answer_text);
      },
    },
  );

  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/ai/chat/stream');
  assert.equal(requests[0].options.method, 'POST');
  assert.equal(requests[0].options.headers.Accept, 'text/event-stream');
  assert.equal(requests[0].options.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(requests[0].options.body), {
    message: '你好',
    context: { page: 'ai' },
  });
  assert.deepEqual(seenEvents, ['ack', 'retrieval_started', 'delta', 'final']);
  assert.deepEqual(seenDeltas, ['最终']);
  assert.equal(result.final.content, '最终答案');
  assert.equal(result.final.citations[0].title, '引用A');
  assert.equal(result.final.suggestions[0].label, '继续问优惠券');
  assert.equal(result.final.shops[0].name, '店铺A');
  assert.equal(result.final.vouchers[0].title, '券A');
  assert.equal(result.final.cards[0].title, '卡片A');
  assert.equal(result.final.nextSteps[0], '继续问优惠券');
  assert.equal(result.final.traceId, 'trace-1');
  assert.equal(result.final.turnId, 'turn-1');
  assert.equal(result.final.sessionId, 'sess-1');
  assert.equal(result.timeline.length, 4);
});

test('streamAssistantPrompt 在 clarification_card 终态下不应抛出缺少 final 的错误', async (t) => {
  const originalFetch = global.fetch;
  global.fetch = async () => {
    return {
      ok: true,
      body: new ReadableStream({
        start(controller) {
          const encoder = new TextEncoder();
          controller.enqueue(encoder.encode('event: ack\n'));
          controller.enqueue(encoder.encode('data: {"traceId":"trace-2","sessionId":"sess-2","turnId":"turn-2","payload":{"message":"accepted"}}\n\n'));
          controller.enqueue(encoder.encode('event: clarification_card\n'));
          controller.enqueue(encoder.encode('data: {"traceId":"trace-2","sessionId":"sess-2","turnId":"turn-2","payload":{"card_id":"clarify-1","question":"请补充店名","options":[{"id":"opt-1","label":"继续补充","value":"继续补充"}],"ambiguity_type":"missing_shop"}}\n\n'));
          controller.close();
        },
      }),
    };
  };
  t.after(() => {
    global.fetch = originalFetch;
  });

  const result = await streamAssistantPrompt({ message: '帮我看看', context: { page: 'ai' } });

  assert.equal(result.final, null);
  assert.equal(result.error, null);
  assert.equal(result.terminalType, 'clarification_card');
  assert.equal(result.timeline.length, 2);
  assert.equal(result.terminalMessage.eventType, 'clarification_card');
  assert.equal(result.terminalMessage.clarificationCard.question, '请补充店名');
  assert.equal(result.terminalMessage.content.includes('需要你补充信息'), true);
});

test('streamAssistantPrompt 在只有增量、没有 final 时会回退成最终消息', async (t) => {
  const originalFetch = global.fetch;
  global.fetch = async () => {
    return {
      ok: true,
      body: new ReadableStream({
        start(controller) {
          const encoder = new TextEncoder();
          controller.enqueue(encoder.encode('event: ack\n'));
          controller.enqueue(encoder.encode('data: {"traceId":"trace-3","sessionId":"sess-3","turnId":"turn-3","payload":{"message":"accepted"}}\n\n'));
          controller.enqueue(encoder.encode('event: delta\n'));
          controller.enqueue(encoder.encode('data: {"traceId":"trace-3","sessionId":"sess-3","turnId":"turn-3","payload":{"delta":"先看券","answer_text":"先看券"}}\n\n'));
          controller.close();
        },
      }),
    };
  };
  t.after(() => {
    global.fetch = originalFetch;
  });

  const result = await streamAssistantPrompt({ message: '有券吗', context: { page: 'ai' } });

  assert.equal(result.final?.content, '先看券');
  assert.equal(result.error, null);
  assert.equal(result.terminalType, 'final');
  assert.equal(result.timeline.length, 2);
});

test('streamAssistantPrompt 在 signal abort 时返回 cancelled 且停止继续消费事件', async (t) => {
  const originalFetch = global.fetch;
  const abortController = new AbortController();
  const seenEvents = [];
  global.fetch = async (url, options) => {
    return {
      ok: true,
      body: new ReadableStream({
        start(controller) {
          const encoder = new TextEncoder();
          options.signal?.addEventListener('abort', () => {
            controller.error(new DOMException('Aborted', 'AbortError'));
          });
          controller.enqueue(encoder.encode('event: ack\n'));
          controller.enqueue(encoder.encode('data: {"traceId":"trace-abort","sessionId":"sess-abort","turnId":"turn-abort","payload":{"message":"accepted"}}\n\n'));
        },
      }),
    };
  };
  t.after(() => {
    global.fetch = originalFetch;
  });

  const result = await streamAssistantPrompt(
    { message: '你好', context: { page: 'ai' } },
    {
      onEvent(event) {
        seenEvents.push(event.type);
        if (event.type === 'ack') {
          abortController.abort();
        }
      },
    },
    {
      signal: abortController.signal,
    },
  );

  assert.deepEqual(seenEvents, ['ack']);
  assert.equal(result.cancelled, true);
  assert.equal(result.final, null);
  assert.equal(result.error, null);
  assert.equal(result.terminalType, 'cancelled');
});

test('submitAssistantFeedback 以上报冻结契约中的最小字段', async (t) => {
  const originalFetch = global.fetch;
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      text: async () => JSON.stringify({
        success: true,
        data: {
          saved: true,
        },
      }),
    };
  };
  t.after(() => {
    global.fetch = originalFetch;
  });

  const payload = {
    sessionId: 'sess-1',
    turnId: 'turn-1',
    traceId: 'trace-1',
    isHelpful: true,
    issueType: '',
    comment: '',
    finalPayload: { answer_text: '最终答案' },
    timeline: [{ type: 'retrieval_started' }],
    context: { page: 'ai' },
  };

  const result = await submitAssistantFeedback(payload);

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/ai/feedback/report');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.headers.Accept, 'application/json');
  assert.equal(calls[0].options.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(calls[0].options.body), payload);
  assert.deepEqual(result, { saved: true });
});

test('submitAssistantApproval 会提交审批结果并返回代理响应', async (t) => {
  const originalFetch = global.fetch;
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      text: async () => JSON.stringify({
        success: true,
        data: {
          accepted: true,
          approval_state: 'approved',
        },
      }),
    };
  };
  t.after(() => {
    global.fetch = originalFetch;
  });

  const payload = {
    sessionId: 'sess-approval-1',
    traceId: 'trace-approval-1',
    turnId: 'turn-approval-1',
    approvalId: 'approval-1',
    decision: 'approved',
    approvalRequest: {
      tool_name: 'create_booking',
      approval_state: 'pending_approval',
    },
  };

  const result = await submitAssistantApproval(payload);

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/ai/approval/submit');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.headers.Accept, 'application/json');
  assert.equal(calls[0].options.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(calls[0].options.body), payload);
  assert.deepEqual(result, {
    accepted: true,
    approval_state: 'approved',
  });
});

test('shouldAutoScrollToLatest 在会话切换或接近底部时返回 true', () => {
  assert.equal(
    shouldAutoScrollToLatest({
      force: true,
      scrollTop: 0,
      scrollHeight: 3000,
      clientHeight: 700,
    }),
    true,
  );

  assert.equal(
    shouldAutoScrollToLatest({
      force: false,
      scrollTop: 650,
      scrollHeight: 1600,
      clientHeight: 800,
    }),
    true,
  );
});

test('shouldAutoScrollToLatest 在用户远离底部时返回 false', () => {
  assert.equal(
    shouldAutoScrollToLatest({
      force: false,
      scrollTop: 0,
      scrollHeight: 3000,
      clientHeight: 700,
    }),
    false,
  );
});

test('appendSessionMessage 会在默认新对话收到首条用户消息后自动生成标题', () => {
  const session = createAssistantSession({ page: 'ai' });
  const next = appendSessionMessage(session, {
    role: 'user',
    content: '帮我推荐附近的火锅店',
  });

  assert.equal(session.title, '新对话');
  assert.equal(next.title, '帮我推荐...');
  assert.equal(next.messages.length, 1);
  assert.equal(next.messages[0].content, '帮我推荐附近的火锅店');
});

test('appendSessionMessage 不会覆盖已有的自定义标题', () => {
  const session = createAssistantSession({ title: '今日攻略', page: 'ai' });
  const next = appendSessionMessage(session, {
    role: 'user',
    content: '再给我补充几家咖啡店',
  });

  assert.equal(next.title, '今日攻略');
  assert.equal(next.messages.length, 1);
});

test('appendSessionMessage 会保留助手消息里的结构化字段', () => {
  const session = createAssistantSession({ page: 'ai' });
  const next = appendSessionMessage(session, {
    role: 'assistant',
    content: '给你整理好了',
    answerContent: '给你整理好了',
    thinkingContent: '先帮你归纳一下',
    suggestions: [{ label: '看优惠券', prompt: '看看优惠券' }],
    shops: [{ id: 1, name: '店铺A' }],
    vouchers: [{ id: 2, title: '券A' }],
    cards: [{ title: '卡片A' }],
    nextSteps: ['继续追问'],
  });

  assert.equal(next.messages.length, 1);
  assert.equal(next.messages[0].content, '给你整理好了');
  assert.equal(next.messages[0].answerContent, '给你整理好了');
  assert.equal(next.messages[0].thinkingContent, '先帮你归纳一下');
  assert.equal(next.messages[0].suggestions[0].prompt, '看看优惠券');
  assert.equal(next.messages[0].shops[0].name, '店铺A');
  assert.equal(next.messages[0].vouchers[0].title, '券A');
  assert.equal(next.messages[0].cards[0].title, '卡片A');
  assert.equal(next.messages[0].nextSteps[0], '继续追问');
});

test('updateSessionMessage 会更新已存在的消息内容并保留消息 id', () => {
  const session = createAssistantSession({ page: 'ai' });
  const appended = appendSessionMessage(session, {
    role: 'assistant',
    content: '中间答案',
    eventType: 'answer_delta',
  });
  const messageId = appended.messages[0].id;
  const updated = updateSessionMessage(appended, messageId, {
    content: '<details open><summary><b>💭 深度思考中...</b></summary>重新整理</details>\n\n最终答案',
  });

  assert.equal(updated.messages[0].id, messageId);
  assert.equal(updated.messages[0].content, '最终答案');
  assert.equal(updated.messages[0].answer, '最终答案');
  assert.equal(updated.messages[0].answerContent, '最终答案');
  assert.equal(updated.messages[0].thinkingContent, '重新整理');
});
