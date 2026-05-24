function firstDefined(...values) {
  return values.find((value) => value !== undefined && value !== null);
}

function normalizeArray(value) {
  return Array.isArray(value) ? value : [];
}

function normalizeObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function firstText(...values) {
  for (const value of values) {
    if (value === undefined || value === null) {
      continue;
    }

    const text = String(value).trim();
    if (text) {
      return text;
    }
  }

  return '';
}

function pickMetaValue(...values) {
  const value = firstDefined(...values);
  return value === undefined || value === null ? '' : String(value);
}

const ASSISTANT_THINKING_OPEN_RE = /<(?:details|think)\b[^>]*>/i;
const ASSISTANT_THINKING_CLOSE_RE = /<\/(?:details|think)>/i;
const ASSISTANT_THINKING_STRIP_RE = /<\/?(?:details|think|summary)[^>]*>/gi;

function stripAssistantThinkingMarkup(value = '') {
  return String(value || '')
    .replace(/<summary[^>]*>[\s\S]*?<\/summary>/i, '')
    .replace(ASSISTANT_THINKING_STRIP_RE, '')
    .trim();
}

export function splitAssistantMessageContent(content = '') {
  const raw = String(content || '');
  if (!raw) {
    return {
      hasThinking: false,
      thinkingContent: '',
      answerContent: '',
    };
  }

  const openMatch = raw.match(ASSISTANT_THINKING_OPEN_RE);
  const closeMatch = raw.match(ASSISTANT_THINKING_CLOSE_RE);

  if (!openMatch && !closeMatch) {
    return {
      hasThinking: false,
      thinkingContent: '',
      answerContent: raw.trim(),
    };
  }

  const openIndex = openMatch?.index ?? -1;
  const openEndIndex = openIndex >= 0 ? openIndex + openMatch[0].length : -1;
  const closeIndex = closeMatch?.index ?? -1;

  if (openIndex >= 0 && closeIndex >= openEndIndex) {
    return {
      hasThinking: true,
      thinkingContent: stripAssistantThinkingMarkup(raw.slice(openEndIndex, closeIndex)),
      answerContent: stripAssistantThinkingMarkup(
        `${raw.slice(0, openIndex)}${raw.slice(closeIndex + closeMatch[0].length)}`,
      ),
    };
  }

  if (openIndex >= 0) {
    return {
      hasThinking: true,
      thinkingContent: stripAssistantThinkingMarkup(raw.slice(openEndIndex)),
      answerContent: stripAssistantThinkingMarkup(raw.slice(0, openIndex)),
    };
  }

  if (closeIndex >= 0) {
    return {
      hasThinking: true,
      thinkingContent: stripAssistantThinkingMarkup(raw.slice(0, closeIndex)),
      answerContent: stripAssistantThinkingMarkup(raw.slice(closeIndex + closeMatch[0].length)),
    };
  }

  return {
    hasThinking: false,
    thinkingContent: '',
    answerContent: raw.trim(),
  };
}

export function normalizeAssistantMessage(message = {}) {
  const source = normalizeObject(message);
  if (source.role !== 'assistant') {
    return { ...source };
  }

  const contentValue = firstText(source.content);
  const rawContent = ASSISTANT_THINKING_OPEN_RE.test(contentValue) || ASSISTANT_THINKING_CLOSE_RE.test(contentValue)
    ? contentValue
    : firstText(source.rawContent, source.raw_content, source.content);
  const parsedContent = splitAssistantMessageContent(rawContent);
  const explicitAnswer = firstText(source.answerContent, source.answer);
  const thinkingContent = firstText(
    source.thinkingContent,
    source.thinking_content,
    parsedContent.thinkingContent,
  );
  let answerContent = parsedContent.answerContent;
  if (!answerContent && !parsedContent.hasThinking) {
    answerContent = explicitAnswer;
  }

  return {
    ...source,
    rawContent,
    content: answerContent,
    answer: answerContent,
    answerContent,
    thinkingContent,
    hasThinking: Boolean(thinkingContent),
  };
}

function normalizePromptItem(item, index = 0) {
  if (typeof item === 'string') {
    const text = String(item || '').trim();
    if (!text) {
      return null;
    }

    return {
      label: text,
      prompt: text,
      icon: '',
      key: `${index}-${text}`,
    };
  }

  const source = normalizeObject(item);
  const prompt = String(firstDefined(source.prompt, source.label, source.title, source.text, source.name, '') || '').trim();
  const label = String(firstDefined(source.label, source.title, source.prompt, source.text, source.name, prompt) || '').trim();
  const icon = String(firstDefined(source.icon, source.avatar, source.badge, '') || '').trim();

  if (!prompt && !label) {
    return null;
  }

  return {
    label: label || prompt,
    prompt: prompt || label,
    icon,
    key: String(firstDefined(source.id, source.key, prompt, label, index)),
  };
}

function normalizeStepItem(item) {
  if (typeof item === 'string') {
    return String(item || '').trim();
  }

  const source = normalizeObject(item);
  return String(firstDefined(source.prompt, source.label, source.title, source.text, source.name, source.step, '') || '').trim();
}

function normalizeClarificationOption(item, index = 0) {
  if (typeof item === 'string') {
    const text = String(item || '').trim();
    if (!text) {
      return null;
    }

    return {
      id: `clarify-${index}`,
      label: text,
      value: text,
      description: '',
      key: `${index}-${text}`,
    };
  }

  const source = normalizeObject(item);
  const label = String(firstDefined(source.label, source.title, source.text, source.prompt, source.name, '') || '').trim();
  const value = String(firstDefined(source.value, source.prompt, source.text, label, '') || '').trim();
  const description = String(firstDefined(source.description, source.desc, source.note, source.tip, '') || '').trim();

  if (!label && !value) {
    return null;
  }

  const key = String(firstDefined(source.id, source.key, value, label, index));
  return {
    id: String(firstDefined(source.id, source.key, index)),
    label: label || value,
    value: value || label,
    description,
    key,
  };
}

export function normalizeClarificationCard(value) {
  const source = normalizeObject(value);
  return {
    cardId: String(firstDefined(source.card_id, source.cardId, source.id, source.key, '') || ''),
    question: String(firstDefined(source.question, source.prompt, source.title, source.message, '') || ''),
    options: normalizeArray(source.options)
      .map((item, index) => normalizeClarificationOption(item, index))
      .filter(Boolean),
    ambiguityType: String(firstDefined(source.ambiguity_type, source.ambiguityType, '') || ''),
  };
}

export function normalizeAssistantSuggestions(items = []) {
  return normalizeArray(items)
    .map((item, index) => normalizePromptItem(item, index))
    .filter((item) => Boolean(item && item.prompt));
}

export function normalizeAssistantNextSteps(items = []) {
  return normalizeArray(items)
    .map((item) => normalizeStepItem(item))
    .filter(Boolean);
}

export function normalizeAssistantResponse(payload) {
  const source = normalizeObject(payload);
  const context = normalizeObject(source.context);
  const answerContent = firstText(source.answerContent, source.answer_content, source.answer_text, source.answer);
  const thinkingContent = firstText(source.thinkingContent, source.thinking_content);

  return {
    answer: answerContent,
    answerContent,
    thinkingContent,
    mode: source.mode || 'faq',
    source: source.source || 'local',
    fallback: Boolean(source.fallback),
    page: source.page || context.page || 'assistant',
    currentTopic: firstDefined(source.currentTopic, source.current_topic, '') || '',
    clarificationCard: normalizeClarificationCard(firstDefined(source.clarificationCard, source.clarification_card)),
    suggestions: normalizeAssistantSuggestions(source.suggestions),
    citations: normalizeArray(source.citations),
    shops: normalizeArray(source.shops),
    vouchers: normalizeArray(source.vouchers),
    cards: normalizeArray(source.cards),
    nextSteps: normalizeAssistantNextSteps(firstDefined(source.nextSteps, source.next_steps)),
    taskChain: normalizeArray(firstDefined(source.taskChain, source.task_chain)),
    context,
    routeDecision: firstDefined(source.routeDecision, source.route_decision, '') || '',
    routeReason: firstDefined(source.routeReason, source.route_reason, '') || '',
    stageTimeline: normalizeArray(firstDefined(source.stageTimeline, source.stage_timeline)),
    retrievalSummary: firstDefined(source.retrievalSummary, source.retrieval_summary, '') || '',
    memoryUsedSummary: firstDefined(source.memoryUsedSummary, source.memory_used_summary, '') || '',
    metrics: normalizeObject(source.metrics),
    approvalRequired: Boolean(firstDefined(source.approvalRequired, source.approval_required)),
    approvalStatus: firstDefined(source.approvalStatus, source.approval_status, '') || '',
    approvalRequest: normalizeObject(firstDefined(source.approvalRequest, source.approval_request)),
    finalPayload: source,
  };
}

export function normalizeAssistantEnvelope(event = {}) {
  const envelope = normalizeObject(event.data);
  const meta = normalizeObject(envelope.meta);
  const payloadSource = firstDefined(envelope.payload, envelope.data, envelope.body, {});
  const payload = normalizeObject(payloadSource);

  return {
    type: String(firstDefined(envelope.event_type, envelope.eventType, event.type, '') || ''),
    payload,
    traceId: pickMetaValue(
      envelope.traceId,
      envelope.trace_id,
      meta.traceId,
      meta.trace_id,
      payload.traceId,
      payload.trace_id,
    ),
    turnId: pickMetaValue(
      envelope.turnId,
      envelope.turn_id,
      meta.turnId,
      meta.turn_id,
      payload.turnId,
      payload.turn_id,
    ),
    sessionId: pickMetaValue(
      envelope.sessionId,
      envelope.session_id,
      meta.sessionId,
      meta.session_id,
      payload.sessionId,
      payload.session_id,
    ),
    envelope,
  };
}

export function buildAssistantTimelineEntry(event = {}, fallbackMeta = {}) {
  const normalized = normalizeAssistantEnvelope(event);
  return {
    type: normalized.type,
    payload: normalized.payload,
    traceId: normalized.traceId || fallbackMeta.traceId || '',
    turnId: normalized.turnId || fallbackMeta.turnId || '',
    sessionId: normalized.sessionId || fallbackMeta.sessionId || '',
    createdAt: new Date().toISOString(),
  };
}

function pickPayloadSummary(payload = {}) {
  return firstDefined(
    payload.answer_text,
    payload.delta,
    payload.message,
    payload.summary,
    payload.question,
    payload.title,
    payload.query,
    payload.tool_name,
    payload.toolName,
    payload.name,
    payload.reason,
    payload.error_message,
    payload.errorMessage,
    '',
  );
}

export function formatAssistantTimelineEntry(entry = {}) {
  const payload = normalizeObject(entry.payload);
  const summary = String(pickPayloadSummary(payload) || '').trim();
  const stageLabel = String(firstDefined(payload.stage, payload.current_stage, '') || '').trim();
  const runningMessage = stageLabel ? `处理中（${stageLabel}）…` : '处理中。';

  const stageMessages = {
    load_context_started: '正在读取与解析会话上下文。',
    load_context_done: '会话上下文已准备完成。',
    intent_analysis_started: '正在分析意图与提取关键槽位。',
    intent_analysis_done: '意图分析完成。',
    query_rewrite_started: '正在改写查询语句。',
    query_rewrite_done: '查询改写完成。',
    retrieval_started: '正在启动检索流程。',
    embedding_started: '正在生成向量表示。',
    embedding_done: '向量生成完成。',
    qdrant_search_started: '正在查询 Qdrant 索引。',
    qdrant_search_done: 'Qdrant 检索完成。',
    rrf_fusion_started: '正在执行 RRF 融合。',
    rrf_fusion_done: 'RRF 融合完成。',
    rerank_started: '正在重排候选证据。',
    rerank_done: '候选证据重排完成。',
    answer_stream_started: '正在生成回答。',
  };

  if (stageMessages[entry.type]) {
    return stageMessages[entry.type];
  }

  if (entry.type === 'heartbeat') {
    return runningMessage;
  }

  if (entry.type === 'clarification_card') {
    return summary ? `需要你补充信息：${summary}` : '需要你补充更多信息后才能继续。';
  }

  if (entry.type === 'retrieval_started') {
    return summary ? `正在检索相关资料：${summary}` : '正在检索相关资料。';
  }

  if (entry.type === 'tool_call') {
    return summary ? `正在调用工具：${summary}` : '正在调用工具。';
  }

  if (entry.type === 'tool_result') {
    return summary ? `工具执行完成：${summary}` : '工具执行完成。';
  }

  if (entry.type === 'approval_required') {
    return summary ? `该操作待确认：${summary}` : '该操作需要你确认后才能继续。';
  }

  if (entry.type === 'retrieval_result') {
    return summary ? `检索完成：${summary}` : '检索完成，正在整理结果。';
  }

  if (entry.type === 'memory_retrieval_started') {
    return summary ? `正在读取会话记忆：${summary}` : '正在读取会话记忆。';
  }

  if (entry.type === 'memory_retrieval_result') {
    return summary ? `会话记忆已载入：${summary}` : '会话记忆已载入。';
  }

  if (entry.type === 'memory_promotion_result') {
    return summary ? `会话记忆已更新：${summary}` : '会话记忆已更新。';
  }

  if (entry.type === 'error') {
    return summary ? `处理失败：${summary}` : '处理失败，请稍后重试。';
  }

  if (entry.type === 'ack') {
    return '';
  }

  if (entry.type === 'delta' || entry.type === 'answer_delta') {
    return '正在生成回答。';
  }

  return summary || '处理中。';
}

export function buildAssistantSystemMessage(entry = {}) {
  const payload = normalizeObject(entry.payload);
  return {
    role: 'system',
    content: formatAssistantTimelineEntry(entry),
    eventType: entry.type || '',
    eventTimeline: [entry],
    traceId: entry.traceId || '',
    turnId: entry.turnId || '',
    sessionId: entry.sessionId || '',
    approvalId: pickMetaValue(payload.approvalId, payload.approval_id, entry.turnId),
    approvalRequired: entry.type === 'approval_required' || Boolean(payload.approval_required || payload.approvalRequired),
    approvalStatus: firstDefined(payload.approval_status, payload.approvalStatus, '') || '',
    approvalRequest: normalizeObject(firstDefined(payload.approval_request, payload.approvalRequest)),
    clarificationCard: normalizeClarificationCard(entry.type === 'clarification_card' ? payload : firstDefined(payload.clarification_card, payload.clarificationCard)),
  };
}

export function buildAssistantSessionMessage(response, meta = {}) {
  const normalized = normalizeAssistantResponse(response);
  const answerContent = firstText(normalized.answerContent, normalized.answer);
  const thinkingContent = firstText(meta.thinkingContent, normalized.thinkingContent);
  const resolvedAnswer = answerContent || '我暂时还没有拿到有效回复，请再试一次。';
  return {
    role: 'assistant',
    content: resolvedAnswer,
    answer: resolvedAnswer,
    answerContent: resolvedAnswer,
    thinkingContent,
    rawContent: firstText(meta.rawContent, resolvedAnswer),
    mode: normalized.mode,
    source: normalized.source,
    fallback: normalized.fallback,
    page: normalized.page,
    currentTopic: normalized.currentTopic,
    suggestions: normalized.suggestions,
    citations: normalized.citations,
    shops: normalized.shops,
    vouchers: normalized.vouchers,
    cards: normalized.cards,
    nextSteps: normalized.nextSteps,
    taskChain: normalized.taskChain,
    context: normalized.context,
    routeDecision: normalized.routeDecision,
    routeReason: normalized.routeReason,
    stageTimeline: normalized.stageTimeline,
    retrievalSummary: normalized.retrievalSummary,
    memoryUsedSummary: normalized.memoryUsedSummary,
    metrics: normalized.metrics,
    approvalRequired: normalized.approvalRequired,
    approvalStatus: normalized.approvalStatus,
    approvalRequest: normalized.approvalRequest,
    clarificationCard: normalized.clarificationCard,
    traceId: pickMetaValue(meta.traceId, response?.traceId, response?.trace_id),
    turnId: pickMetaValue(meta.turnId, response?.turnId, response?.turn_id),
    sessionId: pickMetaValue(meta.sessionId, response?.sessionId, response?.session_id),
    eventTimeline: normalizeArray(meta.eventTimeline),
    finalPayload: normalizeObject(meta.finalPayload || normalized.finalPayload),
  };
}

export function buildAssistantMessagePayload(message, context = {}) {
  return {
    message,
    page: context.page || 'assistant',
    context,
  };
}

export function shouldAutoScrollToLatest({
  force = false,
  scrollTop = 0,
  scrollHeight = 0,
  clientHeight = 0,
  threshold = 160,
} = {}) {
  if (force) {
    return true;
  }

  return scrollHeight - scrollTop - clientHeight <= threshold;
}

function contextTopic(context = {}) {
  return context.shopName || context.blogTitle || context.typeName || context.page || '本地生活';
}

function suggestionSet(context = {}) {
  if (context.shopName) {
    return [
      { label: '看优惠券', prompt: '帮我看看这家店的优惠券' },
      { label: '对比同类店', prompt: '帮我对比附近同类型店' },
      { label: '总结口碑', prompt: '帮我总结这家店的口碑' },
    ];
  }

  if (context.blogTitle) {
    return [
      { label: '继续总结', prompt: '继续帮我总结这篇博客' },
      { label: '找同类店', prompt: '顺着这篇博客找同类店' },
      { label: '看高赞笔记', prompt: '推荐一些高赞探店笔记' },
    ];
  }

  if (context.typeName) {
    return [
      { label: '推荐热门店', prompt: '推荐几家热门店' },
      { label: '看优惠券', prompt: '看看有哪些优惠券' },
      { label: '按预算筛选', prompt: '按人均 100 元以内筛选' },
    ];
  }

  return [
    { label: '推荐附近店', prompt: '推荐附近好评店' },
    { label: '看优惠券', prompt: '推荐几张值得领的券' },
    { label: '对比两家店', prompt: '帮我对比两家店' },
  ];
}

export function buildFallbackAssistantResponse(payload = {}) {
  const context = payload.context || {};
  const topic = contextTopic(context);
  const message = String(payload.message || '').trim();
  const modeLabel = context.assistantMode || context.mode ? `［${context.assistantMode || context.mode}］` : '';
  const promptLabel = context.assistantPrompt ? `，并按「${context.assistantPrompt}」风格` : '';
  const sentence = message
    ? `我先围绕「${topic}」给你一个本地化建议${modeLabel}${promptLabel}：${message}。`
    : `我先围绕「${topic}」给你一份本地化建议${modeLabel}${promptLabel}。`;

  return normalizeAssistantResponse({
    answer: [
      sentence,
      '你可以继续让我看优惠券、对比同类店，或者把商铺详情页的信息直接丢给我。',
    ].join('\n'),
    mode: 'local',
    source: 'local-fallback',
    fallback: true,
    page: payload.page || context.page || 'assistant',
    currentTopic: topic,
    suggestions: suggestionSet(context),
    nextSteps: suggestionSet(context).map((item) => item.prompt),
    context,
  });
}
