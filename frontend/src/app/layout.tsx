'use client';

import React, { createContext, useContext, useState, useEffect } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { usePathname, useRouter } from 'next/navigation';
import Link from 'next/link';
import '../styles/globals.css';
import { ChatView } from '../components/common/ChatView';

// 1. 创建 React Query 客户端实例
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false, // 聚焦窗口时不重复发起 API 请求
      retry: 1, // 失败自动重试 1 次
    },
  },
});

// 2. 简易 Theme Context，用于主题切换
const ThemeContext = createContext<{ theme: 'light' | 'dark'; toggleTheme: () => void }>({
  theme: 'dark',
  toggleTheme: () => {},
});

interface SessionHistoryItem {
  sessionId: string;
  title: string;
  timestamp: number;
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<'light' | 'dark'>('dark');
  
  // ChatGPT 风格状态管理
  const pathname = usePathname();
  const router = useRouter();

  // isChatOpen 为 null 表示未做手动干预，由当前路径决定 (仅在 "/" 根路由下渲染对话)
  const [isChatOpen, setIsChatOpen] = useState<boolean | null>(null);
  const [sessionId, setSessionId] = useState<string>('');
  const [history, setHistory] = useState<SessionHistoryItem[]>([]);
  const [chatInitialQuery, setChatInitialQuery] = useState('');
  
  // 计算最终呈现的 AI 激活状态
  const activeChatOpen = isChatOpen !== null ? isChatOpen : (pathname === '/');

  // 重新从 localStorage 加载历史会话列表
  const reloadHistory = () => {
    const saved = localStorage.getItem('chat_sessions');
    if (saved) {
      try {
        const parsed: any[] = JSON.parse(saved);
        const mapped = parsed.map(item => ({
          sessionId: item.sessionId,
          title: item.title || '无标题会话',
          timestamp: item.timestamp || Date.now(),
        }));
        setHistory(mapped);
        return mapped;
      } catch (e) {
        console.error('Failed to parse chat sessions history: ', e);
      }
    }
    return [];
  };

  // 初始化加载
  useEffect(() => {
    const savedTheme = localStorage.getItem('theme') as 'light' | 'dark';
    if (savedTheme) {
      setTheme(savedTheme);
      document.documentElement.classList.toggle('dark', savedTheme === 'dark');
    } else {
      // 默认使用 dark 主题
      setTheme('dark');
      document.documentElement.classList.add('dark');
      localStorage.setItem('theme', 'dark');
    }

    reloadHistory();
    // 始终开启一个全新的会话，符合“一旦发送消息就新建会话”的设计
    setSessionId(`session-${Date.now()}`);
  }, []);

  // 监听全局打开 Chat 事件
  useEffect(() => {
    const handleOpenChat = (e: any) => {
      // 每次从外部路由触发（如卡片点击）进入对话时，都强制新建一个会话
      setSessionId(`session-${Date.now()}`);
      setChatInitialQuery(e.detail?.query || '');
      setIsChatOpen(true);
      if (window.location.pathname !== '/') {
        router.push('/');
      }
    };
    window.addEventListener('open-ai-chat', handleOpenChat);
    return () => window.removeEventListener('open-ai-chat', handleOpenChat);
  }, [router]);

  const toggleTheme = () => {
    const nextTheme = theme === 'light' ? 'dark' : 'light';
    setTheme(nextTheme);
    localStorage.setItem('theme', nextTheme);
    document.documentElement.classList.toggle('dark', nextTheme === 'dark');
  };

  // 新建会话
  const handleNewChat = () => {
    setSessionId(`session-${Date.now()}`);
    setChatInitialQuery('');
    setIsChatOpen(true);
    if (window.location.pathname !== '/') {
      router.push('/');
    }
  };

  // 切换到某一历史会话
  const handleSelectSession = (id: string) => {
    setSessionId(id);
    setChatInitialQuery('');
    setIsChatOpen(true);
    if (window.location.pathname !== '/') {
      router.push('/');
    }
  };

  // 删除历史会话
  const handleDeleteSession = (e: React.MouseEvent, idToDelete: string) => {
    e.stopPropagation();
    const saved = localStorage.getItem('chat_sessions');
    if (saved) {
      try {
        const parsed: any[] = JSON.parse(saved);
        const filtered = parsed.filter(item => item.sessionId !== idToDelete);
        localStorage.setItem('chat_sessions', JSON.stringify(filtered));
        
        const reloaded = reloadHistory();
        if (idToDelete === sessionId) {
          if (reloaded.length > 0) {
            setSessionId(reloaded[0].sessionId);
          } else {
            setSessionId(`session-${Date.now()}`);
          }
        }
      } catch (err) {
        console.error(err);
      }
    }
  };

  return (
    <html lang="zh-CN" className={theme === 'dark' ? 'dark' : ''}>
      <body className="bg-themeBg-main text-themeText-main font-sans min-h-screen transition-colors duration-300">
        <QueryClientProvider client={queryClient}>
          <ThemeContext.Provider value={{ theme, toggleTheme }}>
            <div className="flex w-full min-h-screen relative overflow-hidden">
              
              {/* 1. 左侧大 Sidebar - ChatGPT 经典暗色面板 */}
              <aside className="w-64 bg-[#171717] text-gray-200 flex flex-col h-screen sticky top-0 shrink-0 z-40 transition-colors duration-300 border-r border-[#262626] shadow-theme-premium">
                
                {/* 品牌 & 新建对话区 */}
                <div className="p-3.5 flex flex-col gap-3 shrink-0">
                  <div className="flex items-center gap-2.5 px-1.5 py-1">
                    <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-primary to-secondary flex items-center justify-center text-white font-extrabold text-lg shadow-theme-md">
                      <span>L</span>
                    </div>
                    <div>
                      <h2 className="font-extrabold text-xs text-white tracking-tight">本地生活 AI 助手</h2>
                      <p className="text-[8px] text-gray-400 uppercase font-bold tracking-wider">Decision Hub</p>
                    </div>
                  </div>
                  
                  {/* 新建会话大按钮 */}
                  <button
                    onClick={handleNewChat}
                    className="w-full flex items-center justify-between px-3 py-2.5 bg-transparent border border-gray-600 hover:bg-[#212121] text-white rounded-xl text-xs font-bold transition-all shadow-theme-sm active:scale-98"
                  >
                    <span>新建对话</span>
                    <span className="text-sm">➕</span>
                  </button>
                </div>

                {/* 2. 历史会话列表 */}
                <div className="flex-1 overflow-y-auto px-2 py-2 flex flex-col gap-1 scrollbar-thin">
                  <p className="text-[8px] font-extrabold text-gray-500 uppercase tracking-widest px-3 mb-1.5">会话历史</p>
                  {history.length === 0 ? (
                    <p className="text-[10px] text-gray-500 text-center py-8">暂无历史对话</p>
                  ) : (
                    history.map((item) => {
                      const isActive = item.sessionId === sessionId && activeChatOpen;
                      return (
                        <div
                          key={item.sessionId}
                          onClick={() => handleSelectSession(item.sessionId)}
                          className={`group flex items-center justify-between px-3 py-2 rounded-xl text-xs cursor-pointer transition-all border border-transparent
                            ${isActive
                              ? 'bg-[#212121] border-[#2f2f2f] text-white font-bold'
                              : 'text-gray-400 hover:bg-[#212121] hover:text-white'}`}
                        >
                          <span className="truncate flex-1 pr-2">💬 {item.title}</span>
                          <button
                            onClick={(e) => handleDeleteSession(e, item.sessionId)}
                            className="opacity-0 group-hover:opacity-100 text-gray-500 hover:text-accent-red font-bold text-sm px-1.5 transition-all"
                            title="删除会话"
                          >
                            ✕
                          </button>
                        </div>
                      );
                    })
                  )}
                </div>

                {/* 3. 系统内置功能导航区 */}
                <div className="p-3 border-t border-[#262626] flex flex-col gap-1 shrink-0 bg-[#171717]">
                  <p className="text-[8px] font-extrabold text-gray-500 uppercase tracking-widest px-2 mb-1.5">系统导航</p>
                  
                  {/* AI 助手主项 */}
                  <button
                    onClick={() => {
                      setIsChatOpen(true);
                      if (window.location.pathname !== '/') {
                        router.push('/');
                      }
                    }}
                    className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-bold transition-all border border-transparent
                      ${activeChatOpen
                        ? 'bg-primary/20 text-primary border-primary/20 shadow-theme-sm' 
                        : 'text-gray-400 hover:bg-[#212121] hover:text-white'}`}
                  >
                    <span className="text-sm">🤖</span>
                    <span>AI 决策助手</span>
                  </button>

                  <Link
                    href="/"
                    onClick={() => setIsChatOpen(false)}
                    className={`flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-bold transition-all border border-transparent ${
                      pathname === '/' && !activeChatOpen
                        ? 'text-primary bg-primary-light/10 border-primary/10 shadow-theme-sm' 
                        : 'text-gray-400 hover:bg-[#212121] hover:text-white'
                    }`}
                  >
                    <span className="text-sm">🏠</span>
                    <span>服务首页</span>
                  </Link>
                  <Link
                    href="/explore"
                    onClick={() => setIsChatOpen(false)}
                    className={`flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-bold transition-all border border-transparent ${
                      pathname === '/explore' && !activeChatOpen
                        ? 'text-primary bg-primary-light/10 border-primary/10 shadow-theme-sm' 
                        : 'text-gray-400 hover:bg-[#212121] hover:text-white'
                    }`}
                  >
                    <span className="text-sm">🧭</span>
                    <span>发现推荐</span>
                  </Link>
                  <Link
                    href="/order"
                    onClick={() => setIsChatOpen(false)}
                    className={`flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-bold transition-all border border-transparent ${
                      pathname === '/order' && !activeChatOpen
                        ? 'text-primary bg-primary-light/10 border-primary/10 shadow-theme-sm' 
                        : 'text-gray-400 hover:bg-[#212121] hover:text-white'
                    }`}
                  >
                    <span className="text-sm">📋</span>
                    <span>我的订单</span>
                  </Link>
                  <Link
                    href="/profile"
                    onClick={() => setIsChatOpen(false)}
                    className={`flex items-center gap-2.5 px-3 py-2 rounded-xl text-xs font-bold transition-all border border-transparent ${
                      pathname === '/profile' && !activeChatOpen
                        ? 'text-primary bg-primary-light/10 border-primary/10 shadow-theme-sm' 
                        : 'text-gray-400 hover:bg-[#212121] hover:text-white'
                    }`}
                  >
                    <span className="text-sm">👤</span>
                    <span>个人中心</span>
                  </Link>
                </div>

                {/* 4. 侧边栏 Footer & 主题与用户 */}
                <div className="p-3 border-t border-[#262626] flex items-center justify-between shrink-0 bg-[#171717]">
                  {/* 用户简卡 */}
                  <div className="flex items-center gap-2" title="北京邮电大学 (游客)">
                    <div className="w-8 h-8 rounded-full bg-secondary-light flex items-center justify-center font-bold text-secondary text-xs border border-secondary/20">
                      <span>U</span>
                    </div>
                    <div className="min-w-0">
                      <p className="text-[10px] font-bold text-white truncate">游客用户</p>
                      <p className="text-[8px] text-gray-500 truncate">北邮校区</p>
                    </div>
                  </div>
                  
                  {/* 主题切换 */}
                  <button
                    onClick={toggleTheme}
                    className="w-7 h-7 rounded-full bg-[#212121] border border-[#2f2f2f] hover:bg-[#262626] flex items-center justify-center transition-colors text-xs text-white"
                    title={theme === 'dark' ? '切换浅色' : '切换深色'}
                  >
                    {theme === 'dark' ? '☀️' : '🌙'}
                  </button>
                </div>

              </aside>

              {/* 2. 右侧主内容视口 (使用 CSS 隐藏/显示以保留 AI 对话挂载和流式状态) */}
              <div className="flex-1 flex flex-col h-screen min-w-0 overflow-hidden bg-themeBg-main relative">
                
                {/* AI 助手大 UI：始终挂载，使用 CSS 控制显隐 */}
                <div className={`flex-grow h-full overflow-hidden ${activeChatOpen ? 'block' : 'hidden'}`}>
                  <ChatView
                    key={sessionId} // 强制绑定 Key 以在会话 ID 切换时重置全部内部状态并自动加载历史
                    sessionId={sessionId}
                    initialQuery={chatInitialQuery}
                    onUpdateHistory={reloadHistory}
                  />
                </div>

                {/* 业务功能页面：始终挂载，使用 CSS 控制显隐 */}
                <div className={`flex-1 flex flex-col h-full overflow-y-auto ${!activeChatOpen ? 'block' : 'hidden'}`}>
                  {/* 顶部 Sticky View Header */}
                  <header className="sticky top-0 z-20 flex items-center justify-between px-8 py-4 bg-themeBg-sidebar/80 backdrop-blur-md border-b border-themeBorder transition-colors duration-300 shrink-0">
                    <div>
                      <h1 className="font-extrabold text-lg text-themeText-main tracking-tight">商户检索与智能推荐</h1>
                      <p className="text-xs text-themeText-muted mt-0.5">为您实时寻找附近最划算、最高评分的团购与代金券服务</p>
                    </div>
                    
                    <div className="flex items-center gap-3">
                      <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-theme-md bg-themeBg-panel border border-themeBorder text-xs font-bold text-themeText-muted">
                        <span>📍</span>
                        <span>北京邮电大学</span>
                      </div>
                      <button
                        onClick={handleNewChat}
                        className="px-4 py-2 text-xs font-bold text-white bg-primary hover:bg-primary-hover rounded-theme-md shadow-theme-sm transition-colors"
                      >
                        新建询问
                      </button>
                    </div>
                  </header>

                  {/* 核心页面路由内容区 */}
                  <main className="flex-grow max-w-7xl w-full mx-auto px-8 py-8">
                    {children}
                  </main>
                </div>
                
              </div>

            </div>
          </ThemeContext.Provider>
        </QueryClientProvider>
      </body>
    </html>
  );
}

const useTheme = () => useContext(ThemeContext);
