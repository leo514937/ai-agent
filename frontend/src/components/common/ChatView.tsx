'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Merchant } from '../../services/types';
import { MerchantCard } from '../merchant/MerchantCard';

interface MessageTiming {
  startedAt?: number;
  firstTokenAt?: number;
  completedAt?: number;
  failedAt?: number;
  elapsedMs?: number;
}

interface Message {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  steps?: string[];
  shops?: Merchant[];
  timing?: MessageTiming;
}

interface SessionHistoryItem {
  sessionId: string;
  title: string;
  timestamp: number;
  messages: Message[];
}

const MessageTimer: React.FC<{ timing?: MessageTiming; isStreaming?: boolean }> = ({ timing, isStreaming }) => {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!isStreaming || !timing?.startedAt || timing.completedAt || timing.failedAt) {
      return;
    }
    const interval = setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => clearInterval(interval);
  }, [isStreaming, timing]);

  if (!timing?.startedAt) return <span>已思考若干秒</span>;

  if (timing.failedAt) {
    const elapsed = Math.round(((timing.elapsedMs || (timing.failedAt - timing.startedAt)) / 1000));
    return <span className="text-accent-red">已中断，用时 {elapsed} 秒</span>;
  }

  if (timing.completedAt) {
    const elapsed = Math.round(((timing.elapsedMs || (timing.completedAt - timing.startedAt)) / 1000));
    return <span>用时 {elapsed} 秒</span>;
  }

  if (isStreaming) {
    const elapsed = Math.round((now - timing.startedAt) / 1000);
    return <span className="text-primary">{elapsed > 2 ? `已思考 ${elapsed} 秒` : `思考中 ${elapsed} 秒`}</span>;
  }

  return <span>已思考若干秒</span>;
};

interface ChatViewProps {
  sessionId: string;
  initialQuery?: string;
  onUpdateHistory?: () => void;
}

export const ChatView: React.FC<ChatViewProps> = ({ sessionId, initialQuery, onUpdateHistory }) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentSteps, setCurrentSteps] = useState<string[]>([]);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const copyMessageText = async (text: string) => {
    const content = text ?? '';
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(content);
        return;
      }

      const textarea = document.createElement('textarea');
      textarea.value = content;
      textarea.setAttribute('readonly', 'true');
      textarea.style.position = 'fixed';
      textarea.style.left = '-9999px';
      textarea.style.top = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    } catch (error) {
      console.error('复制失败:', error);
    }
  };

  const copyIcon = (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-3.5 w-3.5">
      <path d="M16 1.75H8A2.25 2.25 0 0 0 5.75 4v1h-1A2.25 2.25 0 0 0 2.5 7.25v12.5A2.25 2.25 0 0 0 4.75 22h8.5a2.25 2.25 0 0 0 2.25-2.25v-1h1A2.25 2.25 0 0 0 18.75 16v-12A2.25 2.25 0 0 0 16.5 1.75ZM7.25 5V4A.75.75 0 0 1 8 3.25h8A.75.75 0 0 1 16.75 4v12a.75.75 0 0 1-.75.75h-1V7.25A2.25 2.25 0 0 0 12.75 5h-5.5Zm8.25 13v1a.75.75 0 0 1-.75.75h-8.5A.75.75 0 0 1 5.5 19v-12a.75.75 0 0 1 .75-.75h8.5a.75.75 0 0 1 .75.75Z" />
    </svg>
  );

  // 快捷问题提示卡片
  const suggestionCards = [
    {
      title: '🍕 附近美食',
      desc: '推荐一下北京邮电大学附近好吃的火锅或烧烤',
      query: '推荐北京邮电大学附近的火锅或烧烤，要性价比高的',
    },
    {
      title: '⚖️ 商家对比',
      desc: '帮我对比附近的 KTV，哪家代金券力度更大？',
      query: '对比附近评分最高的两家KTV，看看谁的优惠券多，营业状态如何',
    },
    {
      title: '💆 到店SPA',
      desc: '找一家离我最近、评分高的推拿理疗馆',
      query: '推荐离我最近、带团购代金券且评分大于4.5的SPA按摩馆',
    },
    {
      title: '🕒 营业咨询',
      desc: '查询附近理发店的今天最晚营业时间',
      query: '帮我找一家附近有代金券并且晚上营业到很晚的理发美发店',
    },
  ];

  // 1. 根据 sessionId 从 localStorage 初始化加载消息历史
  useEffect(() => {
    if (!sessionId) return;
    const saved = localStorage.getItem('chat_sessions');
    if (saved) {
      try {
        const historyList: SessionHistoryItem[] = JSON.parse(saved);
        const matched = historyList.find(h => h.sessionId === sessionId);
        if (matched) {
          // 修正可能因为强制刷新被中断的消息
          const fixedMessages = matched.messages.map((m, i) => {
            if (m.sender === 'assistant' && i === matched.messages.length - 1) {
              if (m.timing && m.timing.startedAt && !m.timing.completedAt && !m.timing.failedAt) {
                return {
                  ...m,
                  timing: { ...m.timing, failedAt: Date.now() },
                  text: m.text ? m.text + '\n\n⚠️ *[会话被中断]*' : '⚠️ *[会话被中断]*'
                };
              }
            }
            return m;
          });
          setMessages(fixedMessages);
          return;
        }
      } catch (e) {
        console.error('Error loading session from history: ', e);
      }
    }
    // 默认欢迎句式
    setMessages([
      {
        id: 'welcome',
        sender: 'assistant',
        text: '您好！我是您的本地生活 AI 智能助手。我可以帮您推荐周边的美食餐厅、到店服务，并帮您进行多店对比和优惠券营业状态的校验。请随时向我提问！',
      },
    ]);
  }, [sessionId]);

  // 2. 外部传入 initialQuery 时的自动触发
  useEffect(() => {
    if (initialQuery) {
      setInputValue(initialQuery);
      const timer = setTimeout(() => {
        handleSend(initialQuery);
      }, 150);
      return () => clearTimeout(timer);
    }
  }, [initialQuery]);

  // 自动滚动到底部
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, currentSteps, isStreaming]);

  // 3. 将消息写入 localStorage 并更新 layout 历史列表
  const persistMessages = (updatedMessages: Message[]) => {
    if (!sessionId) return;

    // 如果只有一条欢迎消息，不需要保存
    if (updatedMessages.length <= 1) return;

    const saved = localStorage.getItem('chat_sessions');
    let historyList: SessionHistoryItem[] = [];
    if (saved) {
      try {
        historyList = JSON.parse(saved);
      } catch (e) {
        console.error(e);
      }
    }

    const existingIdx = historyList.findIndex(h => h.sessionId === sessionId);
    let title = historyList[existingIdx]?.title || '新会话';

    // 以第一条用户消息为标题
    const firstUserMsg = updatedMessages.find(m => m.sender === 'user');
    if (firstUserMsg) {
      title = firstUserMsg.text.slice(0, 15) + (firstUserMsg.text.length > 15 ? '...' : '');
    }

    const updatedItem: SessionHistoryItem = {
      sessionId,
      title,
      timestamp: Date.now(),
      messages: updatedMessages,
    };

    if (existingIdx > -1) {
      historyList[existingIdx] = updatedItem;
    } else {
      historyList.unshift(updatedItem);
    }

    historyList.sort((a, b) => b.timestamp - a.timestamp);
    localStorage.setItem('chat_sessions', JSON.stringify(historyList));

    if (onUpdateHistory) {
      onUpdateHistory();
    }
  };

  // 4. 中断流式连接
  const handleInterrupt = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setIsStreaming(false);

      const failedAt = Date.now();
      const finalMsgs: Message[] = messages.map((m, idx) => {
        if (idx === messages.length - 1 && m.sender === 'assistant') {
          return {
            ...m,
            text: m.text + '\n\n⚠️ *[已停止生成]*',
            timing: {
              ...m.timing,
              failedAt,
              elapsedMs: m.timing?.startedAt ? failedAt - m.timing.startedAt : undefined,
            }
          };
        }
        return m;
      });
      setMessages(finalMsgs);
      setCurrentSteps(prev => [...prev, '⏹ 已经停止生成']);
      persistMessages(finalMsgs);
    }
  };

  // 5. 发送消息逻辑 (流式)
  const handleSend = async (textToSend?: string) => {
    const text = (textToSend || inputValue).trim();
    if (!text || isStreaming) return;

    if (!textToSend) {
      setInputValue('');
    }

    // 用户消息
    const userMsg: Message = { id: `user-${Date.now()}`, sender: 'user', text };
    const initialMsgs = [...messages, userMsg];
    setMessages(initialMsgs);
    setIsStreaming(true);
    setCurrentSteps(['⚡ 正在连接智能决策中枢...']);

    // 助手占位消息
    const assistantMsgId = `assistant-${Date.now()}`;
    const startTime = Date.now();
    const placeholderMsg: Message = {
      id: assistantMsgId,
      sender: 'assistant',
      text: '',
      timing: { startedAt: startTime }
    };
    const stageMsgs = [...initialMsgs, placeholderMsg];
    setMessages(stageMsgs);
    persistMessages(stageMsgs);

    const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8081';
    let streamText = '';
    let finalShops: Merchant[] = [];
    let currentTraceSteps: string[] = stageMsgs[stageMsgs.length - 1].steps || [];
    let firstTokenAt: number | undefined = undefined;
    let currentMsgs = stageMsgs;

    const updateAssistantState = (updates: Partial<Message>) => {
      currentMsgs = currentMsgs.map(m =>
        m.id === assistantMsgId ? { ...m, ...updates, timing: { ...m.timing, ...updates.timing } } : m
      );
      setMessages(currentMsgs);
      persistMessages(currentMsgs);
    };

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const response = await fetch(`${apiBaseUrl}/ai/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('auth_token') || ''}`,
          'X-User-Latitude': localStorage.getItem('user_latitude') || '39.961554',
          'X-User-Longitude': localStorage.getItem('user_longitude') || '116.358104',
        },
        body: JSON.stringify({
          message: text,
          sessionId: sessionId,
          traceId: `trace-${Date.now()}`,
          turnId: `turn-${Date.now()}`,
          page: 'chat_view_large',
          context: {
            user_latitude: parseFloat(localStorage.getItem('user_latitude') || '39.961554'),
            user_longitude: parseFloat(localStorage.getItem('user_longitude') || '116.358104'),
          },
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error('网络请求异常，请确认后端 Java 服务已正常启动。');
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (reader) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const cleanLine = line.trim();
          if (cleanLine.startsWith('data:')) {
            const dataStr = cleanLine.slice(5).trim();
            try {
              const envelope = JSON.parse(dataStr);
              const eventType = envelope.event_type;
              const payload = envelope.payload;

              switch (eventType) {
                case 'trace_started':
                  currentTraceSteps = ['⚡ 会话路由调度中...'];
                  setCurrentSteps([...currentTraceSteps]);
                  updateAssistantState({ steps: [...currentTraceSteps] });
                  break;
                case 'input_normalized':
                  currentTraceSteps.push('📝 输入安全防御与规范化校验已通过');
                  setCurrentSteps([...currentTraceSteps]);
                  updateAssistantState({ steps: [...currentTraceSteps] });
                  break;
                case 'intent_detected':
                  currentTraceSteps.push(`🎯 意图识别成功：${payload.top_intent === 'local_life' ? '本地生活服务' : payload.top_intent}`);
                  setCurrentSteps([...currentTraceSteps]);
                  updateAssistantState({ steps: [...currentTraceSteps] });
                  break;
                case 'semantic_frame_ready':
                  currentTraceSteps.push(`🔍 语义解析已完成。解析模式：${payload.task_type || '通用'}`);
                  setCurrentSteps([...currentTraceSteps]);
                  updateAssistantState({ steps: [...currentTraceSteps] });
                  break;
                case 'target_resolved':
                  currentTraceSteps.push(`📍 关联商户定位：${payload.resolve_status}`);
                  setCurrentSteps([...currentTraceSteps]);
                  updateAssistantState({ steps: [...currentTraceSteps] });
                  break;
                case 'task_planned':
                  currentTraceSteps.push(`📋 执行规划：大模型编排工具链，计划包含 ${payload.tool_call_count || 1} 个底层工具调用`);
                  setCurrentSteps([...currentTraceSteps]);
                  updateAssistantState({ steps: [...currentTraceSteps] });
                  break;
                case 'tool_call_started':
                  currentTraceSteps.push(`⚙️ 正在执行系统查询：${payload.tool_name}...`);
                  setCurrentSteps([...currentTraceSteps]);
                  updateAssistantState({ steps: [...currentTraceSteps] });
                  break;
                case 'tool_call_finished':
                  currentTraceSteps.push(`✅ 数据拉取完成：${payload.tool_name}，状态: ${payload.status}`);
                  setCurrentSteps([...currentTraceSteps]);
                  updateAssistantState({ steps: [...currentTraceSteps] });
                  break;
                case 'evidence_built':
                  currentTraceSteps.push(`📊 数据汇总：真实证据包已装配完毕`);
                  setCurrentSteps([...currentTraceSteps]);
                  updateAssistantState({ steps: [...currentTraceSteps] });
                  break;
                case 'answer_plan_built':
                  currentTraceSteps.push('🤖 语言模型正在校验语气与事实正确性，生成中...');
                  setCurrentSteps([...currentTraceSteps]);
                  updateAssistantState({ steps: [...currentTraceSteps] });
                  break;
                case 'answer_delta':
                  if (payload.delta_text) {
                    if (!firstTokenAt) firstTokenAt = Date.now();
                    streamText += payload.delta_text;
                    updateAssistantState({
                      text: streamText,
                      steps: [...currentTraceSteps],
                      timing: { firstTokenAt }
                    });
                  }
                  break;
                case 'final':
                  if (payload.answer_text) {
                    streamText = payload.answer_text;
                  }
                  if (payload.shops || payload.cards) {
                    const shopList = payload.shops || payload.cards;
                    finalShops = shopList.map((shop: any) => ({
                      id: String(shop.id || shop.shop_id),
                      name: shop.name || '',
                      coverImage: shop.image || shop.cover_image || '/imgs/blogs/blog1.jpg',
                      rating: parseFloat(shop.score || shop.rating || '4.5'),
                      commentCount: parseInt(shop.comments || shop.comment_count || '0'),
                      avgPrice: parseFloat(shop.avg_price || '0'),
                      category: shop.category || '服务',
                      address: shop.address || '',
                      distanceKm: parseFloat(shop.distance || shop.distance_km || '0') / 1000.0,
                      tags: shop.tags || (shop.area ? [shop.area] : []),
                      hasCoupon: !!shop.has_coupon || !!shop.hasCoupon,
                      couponTip: shop.top_coupon_title || shop.coupon_tip || null,
                    }));
                  }
                  break;
                case 'error':
                  streamText = `❌ 发生错误 (${payload.code})：${payload.message}`;
                  break;
                default:
                  break;
              }
            } catch (err) {
              // Ignore parsing errors for raw logs
            }
          }
        }
      }

      const completedAt = Date.now();
      updateAssistantState({
        text: streamText || 'AI 助手当前未返回表述内容。',
        steps: [...currentTraceSteps],
        shops: finalShops,
        timing: {
          firstTokenAt,
          completedAt,
          elapsedMs: startTime ? completedAt - startTime : undefined,
        }
      });
    } catch (err: any) {
      if (err.name === 'AbortError') {
        console.log('API stream aborted by user');
      } else {
        const failedAt = Date.now();
        updateAssistantState({
          text: `❌ 异常：${err.message || '网络连接超时或无法触达后端服务'}`,
          steps: [...currentTraceSteps],
          timing: {
            firstTokenAt,
            failedAt,
            elapsedMs: startTime ? failedAt - startTime : undefined,
          }
        });
      }
    } finally {
      setIsStreaming(false);
      abortControllerRef.current = null;
      setCurrentSteps([]);
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-themeBg-main relative">

      {/* 1. 消息区 */}
      <div
        ref={chatContainerRef}
        className="flex-1 overflow-y-auto px-4 md:px-8 py-6 flex flex-col gap-6 scrollbar-thin pb-36"
      >
        {messages.length <= 1 && (
          // 首屏：ChatGPT 经典的清爽引导首屏
          <div className="max-w-3xl mx-auto w-full flex flex-col items-center justify-center my-auto py-12">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-primary to-secondary flex items-center justify-center text-white text-3xl font-extrabold shadow-theme-lg animate-bounce">
              🤖
            </div>
            <h2 className="text-2xl font-extrabold text-themeText-main tracking-tight mt-6 mb-2">
              您好，我是本地生活决策助手
            </h2>
            <p className="text-xs text-themeText-muted font-semibold mb-10 text-center max-w-lg">
              我已与大众点评商户及优惠数据库连通，支持流式实时决策与可信审计。您可以试着选择下方推荐话题开始咨询：
            </p>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 w-full">
              {suggestionCards.map((card, idx) => (
                <div
                  key={idx}
                  onClick={() => handleSend(card.query)}
                  className="p-4 rounded-theme-lg border border-themeBorder bg-themeBg-card shadow-theme-sm hover:shadow-theme-md hover:border-primary/30 hover:-translate-y-0.5 cursor-pointer transition-all flex flex-col gap-1.5 group text-left"
                >
                  <h4 className="text-xs font-bold text-themeText-main group-hover:text-primary transition-colors">
                    {card.title}
                  </h4>
                  <p className="text-[10px] text-themeText-muted leading-relaxed">
                    {card.desc}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {messages.length > 1 && (
          // 消息流内容：居中限制宽度 w-full max-w-3xl
          <div className="max-w-3xl mx-auto w-full flex flex-col gap-6">
            {messages.map((msg, idx) => {
              const isUser = msg.sender === 'user';
              return (
                <div
                  key={msg.id}
                  className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'}`}
                >
                  {/* 消息内容：用户有气泡，AI没有气泡且没有头像 */}
                  {isUser ? (
                    <div className="relative max-w-[70%] pb-7">
                      <div className="bg-gray-200 dark:bg-[#2f2f2f] text-gray-900 dark:text-gray-100 rounded-2xl px-4 py-2.5 shadow-theme-sm text-xs font-semibold whitespace-pre-wrap select-text">
                        {msg.text}
                      </div>
                      <button
                        type="button"
                        onClick={() => copyMessageText(msg.text)}
                        className="absolute right-1 bottom-0 inline-flex items-center justify-center rounded-md border border-themeBorder bg-themeBg-card/95 p-1.5 text-themeText-muted shadow-sm transition-colors hover:text-primary hover:border-primary/30"
                        title="复制消息"
                        aria-label="复制用户消息"
                      >
                        {copyIcon}
                      </button>
                    </div>
                  ) : (
                    <div className="flex flex-col gap-3 w-full items-start">
                      <div className="relative w-full pb-7">
                        <div className="text-xs text-themeText-main leading-relaxed py-1 whitespace-pre-wrap select-text w-full">
                          {msg.text}
                        </div>
                        <button
                          type="button"
                          onClick={() => copyMessageText(msg.text)}
                          className="absolute left-0 bottom-0 inline-flex items-center justify-center rounded-md border border-themeBorder bg-themeBg-card/95 p-1.5 text-themeText-muted shadow-sm transition-colors hover:text-primary hover:border-primary/30"
                          title="复制消息"
                          aria-label="复制助手消息"
                        >
                          {copyIcon}
                        </button>
                      </div>

                      {/* 推理链与卡片组件：放在文本流下方，无背景气泡 */}
                      <div className="w-full flex flex-col gap-3">
                        {/* 计时器与推理链轨迹 */}
                        {(msg.timing || (msg.steps && msg.steps.length > 0)) && (
                          <details className="mt-1 group" open={isStreaming && idx === messages.length - 1}>
                            <summary className={`text-[11px] text-themeText-light select-none list-none [&::-webkit-details-marker]:hidden hover:text-themeText-muted transition-colors outline-none flex items-center gap-1 font-medium ${msg.steps && msg.steps.length > 0 ? 'cursor-pointer' : 'pointer-events-none'}`}>
                              <MessageTimer timing={msg.timing} isStreaming={isStreaming && idx === messages.length - 1} />
                              {msg.steps && msg.steps.length > 0 && (
                                <span className="text-primary/70 group-open:rotate-90 transition-transform">▸</span>
                              )}                            </summary>
                            {msg.steps && msg.steps.length > 0 && (
                              <div className="mt-1.5 pl-3.5 border-l border-themeBorder text-[9px] font-mono text-themeText-muted flex flex-col gap-1.5 leading-relaxed">
                                {msg.steps.map((step, stepIdx) => (
                                  <div key={stepIdx} className="flex gap-1.5">
                                    <span className="text-primary shrink-0">▸</span>
                                    <span>{step}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </details>
                        )}

                        {/* 店铺决策推荐卡片 */}
                        {msg.shops && msg.shops.length > 0 && (
                          <div className="mt-2 flex flex-col gap-3 w-full max-w-md">
                            <p className="text-[10px] font-extrabold text-secondary flex items-center gap-1">
                              <span>✨</span> 本次决策推荐店铺列表：
                            </p>
                            <div className="flex flex-col gap-3">
                              {msg.shops.map((shop) => (
                                <div
                                  key={shop.id}
                                  onClick={() => {
                                    window.location.href = `/merchants/${shop.id}`;
                                  }}
                                  className="cursor-pointer hover:scale-101 active:scale-99 transition-all"
                                >
                                  <MerchantCard merchant={shop} />
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}

            {/* SSE 正在加载指示 */}
            {isStreaming && (
              <div className="flex flex-col gap-2.5 w-full justify-start">
                <div className="flex items-center gap-2.5 py-1 text-xs text-themeText-light">
                  <div className="flex space-x-1 shrink-0">
                    <div className="w-1.5 h-1.5 bg-primary rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                    <div className="w-1.5 h-1.5 bg-primary rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                    <div className="w-1.5 h-1.5 bg-primary rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                  </div>
                  <span className="font-semibold">决策中枢正在读取商户库并评估执行计划...</span>
                </div>

                {currentSteps.length > 0 && (
                  <div className="mt-1.5 pl-3.5 border-l border-primary/20 text-[9px] font-mono text-themeText-muted flex flex-col gap-1 w-72 md:w-96 animate-pulse-subtle">
                    <p className="font-extrabold text-primary text-[8px] uppercase tracking-wider mb-1 shrink-0">⚙️ 实时推理链路（LangGraph 节点）</p>
                    {currentSteps.map((step, idx) => (
                      <div key={idx} className="flex gap-1.5">
                        <span className="text-primary shrink-0">▸</span>
                        <span className="truncate">{step}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* 2. 底部悬浮输入框区 */}
      <footer className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-themeBg-main via-themeBg-main/95 to-transparent pb-6 pt-8 px-4 md:px-8 shrink-0 z-10">
        <div className="max-w-3xl mx-auto w-full flex flex-col gap-2.5">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSend();
            }}
            className="relative flex items-center bg-themeBg-card border border-themeBorder rounded-2xl shadow-theme-lg px-4 py-2.5 focus-within:border-primary/40 focus-within:ring-1 focus-within:ring-primary/20 transition-all"
          >
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              disabled={isStreaming}
              placeholder={isStreaming ? '正在生成流式答复中...' : '给 AI 决策助手发送消息 (如: 对比附近的KTV)'}
              className="flex-1 bg-transparent text-xs font-semibold text-themeText-main placeholder:text-themeText-light focus:outline-none pr-12 py-1"
            />
            <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center">
              {isStreaming ? (
                <button
                  type="button"
                  onClick={handleInterrupt}
                  className="w-8 h-8 bg-accent-red hover:bg-red-600 text-white rounded-full transition-all shadow-theme-sm active:scale-95 flex items-center justify-center border border-accent-red"
                  title="停止生成"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4">
                    <rect x="6" y="6" width="12" height="12" rx="1.5" />
                  </svg>
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!inputValue.trim()}
                  className="w-8 h-8 bg-primary hover:bg-primary-hover disabled:bg-themeBg-panel disabled:text-themeText-light text-white rounded-full transition-all shadow-theme-sm active:scale-95 disabled:active:scale-100 flex items-center justify-center border border-primary disabled:border-themeBorder"
                  title="发送"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4">
                    <path fillRule="evenodd" d="M12 20.25a.75.75 0 0 1-.75-.75V6.31L6.53 11.03a.75.75 0 0 1-1.06-1.06l6-6a.75.75 0 0 1 1.06 0l6 6a.75.75 0 1 1-1.06 1.06l-4.72-4.72V19.5a.75.75 0 0 1-.75.75Z" clipRule="evenodd" />
                  </svg>
                </button>
              )}
            </div>
          </form>

          <div className="flex items-center justify-between text-[8px] text-themeText-light px-2 font-bold tracking-wide">
            <span>会话 ID: {sessionId}</span>
            <span className="flex items-center gap-1">
              <span>📍 GPS 定位已接入：北京邮电大学</span>
              <span className="w-1.5 h-1.5 rounded-full bg-accent-green animate-pulse" />
            </span>
          </div>
        </div>
      </footer>

    </div>
  );
};
