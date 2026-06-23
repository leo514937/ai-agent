'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Merchant } from '../../services/types';
import { MerchantCard } from '../merchant/MerchantCard';

interface Message {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  steps?: string[];
  shops?: Merchant[];
}

interface SessionHistoryItem {
  sessionId: string;
  title: string;
  timestamp: number;
  messages: Message[];
}

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
          setMessages(matched.messages);
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

      const finalMsgs: Message[] = messages.map((m, idx) => {
        if (idx === messages.length - 1 && m.sender === 'assistant') {
          return {
            ...m,
            text: m.text + '\n\n⚠️ *[会话已被用户手动中断]*',
          };
        }
        return m;
      });
      setMessages(finalMsgs);
      setCurrentSteps(prev => [...prev, '⏹ 会话已被用户手动中断']);
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
    const placeholderMsg: Message = { id: assistantMsgId, sender: 'assistant', text: '' };
    const stageMsgs = [...initialMsgs, placeholderMsg];
    setMessages(stageMsgs);

    const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8081';
    let streamText = '';
    let finalShops: Merchant[] = [];
    let currentTraceSteps: string[] = stageMsgs[stageMsgs.length - 1].steps || [];

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
                  break;
                case 'input_normalized':
                  currentTraceSteps.push('📝 输入安全防御与规范化校验已通过');
                  setCurrentSteps([...currentTraceSteps]);
                  break;
                case 'intent_detected':
                  currentTraceSteps.push(`🎯 意图识别成功：${payload.top_intent === 'local_life' ? '本地生活服务' : payload.top_intent}`);
                  setCurrentSteps([...currentTraceSteps]);
                  break;
                case 'semantic_frame_ready':
                  currentTraceSteps.push(`🔍 语义解析已完成。解析模式：${payload.task_type || '通用'}`);
                  setCurrentSteps([...currentTraceSteps]);
                  break;
                case 'target_resolved':
                  currentTraceSteps.push(`📍 关联商户定位：${payload.resolve_status}`);
                  setCurrentSteps([...currentTraceSteps]);
                  break;
                case 'task_planned':
                  currentTraceSteps.push(`📋 执行规划：大模型编排工具链，计划包含 ${payload.tool_call_count || 1} 个底层工具调用`);
                  setCurrentSteps([...currentTraceSteps]);
                  break;
                case 'tool_call_started':
                  currentTraceSteps.push(`⚙️ 正在执行系统查询：${payload.tool_name}...`);
                  setCurrentSteps([...currentTraceSteps]);
                  break;
                case 'tool_call_finished':
                  currentTraceSteps.push(`✅ 数据拉取完成：${payload.tool_name}，状态: ${payload.status}`);
                  setCurrentSteps([...currentTraceSteps]);
                  break;
                case 'evidence_built':
                  currentTraceSteps.push(`📊 数据汇总：真实证据包已装配完毕`);
                  setCurrentSteps([...currentTraceSteps]);
                  break;
                case 'answer_plan_built':
                  currentTraceSteps.push('🤖 语言模型正在校验语气与事实正确性，生成中...');
                  setCurrentSteps([...currentTraceSteps]);
                  break;
                case 'answer_delta':
                  if (payload.delta_text) {
                    streamText += payload.delta_text;
                    setMessages((prev) =>
                      prev.map((msg) =>
                        msg.id === assistantMsgId
                          ? { ...msg, text: streamText, steps: [...currentTraceSteps] }
                          : msg
                      )
                    );
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

      const finalMsgs: Message[] = stageMsgs.map((msg) =>
        msg.id === assistantMsgId
          ? {
              ...msg,
              text: streamText || 'AI 助手当前未返回表述内容。',
              steps: [...currentTraceSteps],
              shops: finalShops,
            }
          : msg
      );
      setMessages(finalMsgs);
      persistMessages(finalMsgs);
    } catch (err: any) {
      if (err.name === 'AbortError') {
        console.log('API stream aborted by user');
      } else {
        const errorMsgs: Message[] = stageMsgs.map((msg) =>
          msg.id === assistantMsgId
            ? { ...msg, text: `❌ 异常：${err.message || '网络连接超时或无法触达后端服务'}` }
            : msg
        );
        setMessages(errorMsgs);
        persistMessages(errorMsgs);
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
            {messages.map((msg) => {
              const isUser = msg.sender === 'user';
              return (
                <div
                  key={msg.id}
                  className={`flex gap-4 w-full ${isUser ? 'justify-end' : 'justify-start'}`}
                >
                  {/* AI 头像 */}
                  {!isUser && (
                    <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-secondary flex items-center justify-center text-white text-sm font-extrabold shadow-theme-sm shrink-0">
                      AI
                    </div>
                  )}

                  {/* 消息气泡内容 */}
                  <div className={`flex flex-col gap-2 max-w-[85%] ${isUser ? 'items-end' : 'items-start'}`}>
                    <div
                      className={`rounded-theme-lg px-4 py-3 text-xs leading-relaxed border shadow-theme-sm
                        ${isUser 
                          ? 'bg-primary text-white border-primary rounded-tr-none' 
                          : 'bg-themeBg-card text-themeText-main border-themeBorder rounded-tl-none'}`}
                    >
                      <div className="whitespace-pre-wrap">{msg.text}</div>
                    </div>

                    {/* 推理链与卡片组件 */}
                    {!isUser && (
                      <div className="w-full flex flex-col gap-3">
                        {/* 推理链轨迹 */}
                        {msg.steps && msg.steps.length > 0 && (
                          <details className="mt-1 group">
                            <summary className="text-[9px] font-extrabold text-themeText-light cursor-pointer select-none hover:text-themeText-muted transition-colors outline-none">
                              ⚡ 查看大模型推理链与工具调用轨迹 ({msg.steps.length} 步)
                            </summary>
                            <div className="mt-1.5 p-3 rounded-theme-md bg-themeBg-panel border border-themeBorder text-[9px] font-mono text-themeText-muted flex flex-col gap-1.5 leading-relaxed">
                              {msg.steps.map((step, idx) => (
                                <div key={idx} className="flex gap-1.5">
                                  <span className="text-primary-hover shrink-0">▸</span>
                                  <span>{step}</span>
                                </div>
                              ))}
                            </div>
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
                    )}
                  </div>

                  {/* 用户头像 */}
                  {isUser && (
                    <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center text-primary text-sm font-extrabold shadow-theme-sm shrink-0">
                      U
                    </div>
                  )}
                </div>
              );
            })}

            {/* SSE 正在加载指示 */}
            {isStreaming && (
              <div className="flex gap-4 w-full justify-start animate-pulse-subtle">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-secondary flex items-center justify-center text-white text-sm font-extrabold shadow-theme-sm shrink-0 animate-spin-slow">
                  AI
                </div>
                <div className="flex flex-col gap-2.5 max-w-[85%]">
                  <div className="rounded-theme-lg px-4 py-3 bg-themeBg-panel border border-themeBorder text-xs text-themeText-light flex items-center gap-2.5 shadow-theme-sm">
                    <div className="flex space-x-1 shrink-0">
                      <div className="w-1.5 h-1.5 bg-primary rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                      <div className="w-1.5 h-1.5 bg-primary rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                      <div className="w-1.5 h-1.5 bg-primary rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                    </div>
                    <span>决策中枢正在读取商户库并评估执行计划...</span>
                  </div>
                  
                  {currentSteps.length > 0 && (
                    <div className="p-3 rounded-theme-md bg-themeBg-panel border border-themeBorder text-[9px] font-mono text-themeText-muted flex flex-col gap-1 w-72 md:w-96 shadow-theme-sm">
                      <p className="font-extrabold text-primary text-[8px] uppercase tracking-wider mb-1 shrink-0">⚙️ 实时推理链路（LangGraph 节点）</p>
                      {currentSteps.map((step, idx) => (
                        <div key={idx} className="flex gap-1.5">
                          <span className="text-primary-hover shrink-0">▸</span>
                          <span className="truncate">{step}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
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
              className="flex-1 bg-transparent text-xs font-semibold text-themeText-main placeholder:text-themeText-light focus:outline-none pr-24 py-1"
            />
            <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-2">
              {isStreaming ? (
                <button
                  type="button"
                  onClick={handleInterrupt}
                  className="px-3.5 py-1.5 bg-accent-red hover:bg-red-600 text-white text-[10px] font-bold rounded-xl transition-all shadow-theme-sm active:scale-95 flex items-center justify-center gap-1 border border-accent-red"
                >
                  <span>⏹</span> 中断
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!inputValue.trim()}
                  className="px-3.5 py-1.5 bg-primary hover:bg-primary-hover disabled:bg-themeBg-panel disabled:text-themeText-light text-white text-[10px] font-bold rounded-xl transition-all shadow-theme-sm active:scale-95 disabled:active:scale-100 flex items-center justify-center border border-primary disabled:border-themeBorder"
                >
                  发送
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
