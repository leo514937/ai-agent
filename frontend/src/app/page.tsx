'use client';

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../services/api-client';
import { Merchant } from '../services/types';
import { MerchantCard } from '../components/merchant/MerchantCard';
import { Skeleton } from '../components/ui/Skeleton';

// 1. 骨架屏占位卡片组件 (升级为桌面卡片风格)
const MerchantSkeleton = () => (
  <div className="flex flex-col rounded-theme-lg border border-themeBorder bg-themeBg-card p-4 shadow-theme-sm animate-pulse">
    <div className="aspect-[4/3] w-full rounded-theme-md bg-themeBg-panel" />
    <div className="mt-4 h-5 w-2/3 rounded bg-themeBg-panel" />
    <div className="mt-3 flex items-center justify-between">
      <div className="h-4 w-1/3 rounded bg-themeBg-panel" />
      <div className="h-4 w-1/4 rounded bg-themeBg-panel" />
    </div>
    <div className="my-3 border-t border-themeBorder" />
    <div className="h-4 w-1/2 rounded bg-themeBg-panel" />
  </div>
);

// 2. API 获取服务：拉取附近商户，基于分类筛选
const fetchMerchants = async (category?: string): Promise<Merchant[]> => {
  const url = category ? `/merchants?category=${encodeURIComponent(category)}` : '/merchants';
  const response = await apiClient.get<Merchant[]>(url);
  return response;
};

export default function HomePage() {
  const [selectedCategory, setSelectedCategory] = useState<string>('');

  // 3. TanStack Query 自动拉取与状态管理
  const { data: merchants, isLoading, isError, error, refetch } = useQuery<Merchant[]>({
    queryKey: ['merchants', selectedCategory],
    queryFn: () => fetchMerchants(selectedCategory),
  });

  const categories = ['全部', '美食', '休闲娱乐', '美容SPA', '到店服务'];

  return (
    <div className="flex flex-col gap-8">
      
      {/* 1. 桌面端 Premium Hero 广告位 Banner */}
      <section className="bg-gradient-to-br from-primary/5 to-secondary/5 border border-themeBorder rounded-theme-xl p-8 relative overflow-hidden flex flex-col justify-center">
        {/* 背景光晕装饰 */}
        <div className="absolute right-0 top-0 w-80 h-80 rounded-full bg-primary/10 blur-[100px] -z-10" />
        <div className="absolute left-1/3 bottom-0 w-60 h-60 rounded-full bg-secondary/5 blur-[80px] -z-10" />
        
        <span className="self-start inline-block px-3 py-1 bg-primary/10 border border-primary/20 text-primary text-[10px] font-bold rounded-full uppercase tracking-wider mb-4">
          ✨ 智能推荐引擎
        </span>
        <h2 className="font-extrabold text-2xl lg:text-3xl text-themeText-main tracking-tight leading-tight mb-3">
          开启您身边的智能品质生活
        </h2>
        <p className="text-sm text-themeText-muted max-w-2xl leading-relaxed mb-6">
          融合大模型 AI 决策框架，汇聚海量真实商家优惠与特惠服务。支持智能多店横向对比、距离最优推荐、以及可信评论安全校验，让您的消费决策变得无比高效、轻松。
        </p>
        <div className="flex items-center gap-4">
          <button
            onClick={() => {
              if (typeof window !== 'undefined') {
                window.dispatchEvent(new CustomEvent('open-ai-chat', { detail: { query: '' } }));
              }
            }}
            className="px-5 py-2.5 rounded-theme-md text-xs font-bold text-white bg-primary hover:bg-primary-hover shadow-theme-md transition-all"
          >
            开始对话调优
          </button>
          <button
            onClick={() => {
              if (typeof window !== 'undefined') {
                window.dispatchEvent(new CustomEvent('open-ai-chat', { detail: { query: '什么是可信校验与横切防线？' } }));
              }
            }}
            className="px-5 py-2.5 rounded-theme-md text-xs font-bold text-themeText-muted bg-themeBg-card border border-themeBorder hover:bg-themeBg-panel transition-all"
          >
            了解横切校验
          </button>
        </div>
      </section>

      {/* 2. 页面中段：分类 pill 过滤器与状态汇总 */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-themeBorder pb-5">
        <div className="flex items-center gap-2 overflow-x-auto scrollbar-none py-1">
          {categories.map((cat) => {
            const isSelected = (cat === '全部' && !selectedCategory) || selectedCategory === cat;
            return (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat === '全部' ? '' : cat)}
                className={`px-4 py-2 rounded-theme-md text-xs font-bold shrink-0 transition-all border
                  ${isSelected 
                    ? 'bg-primary border-primary text-white shadow-theme-sm' 
                    : 'bg-themeBg-card border-themeBorder text-themeText-muted hover:bg-themeBg-panel hover:text-themeText-main'
                  }`}
              >
                {cat}
              </button>
            );
          })}
        </div>
        <div className="text-xs font-semibold text-themeText-light flex items-center gap-1.5 self-end sm:self-center">
          <span>附近检索到：</span>
          <span className="text-themeText-main font-bold">{merchants ? merchants.length : 0}</span>
          <span>家相关商户</span>
        </div>
      </div>

      {/* 3. 错误状态展示 */}
      {isError && (
        <div className="py-16 flex flex-col items-center justify-center text-center gap-4 bg-themeBg-card border border-themeBorder rounded-theme-lg">
          <span className="text-4xl text-accent-red">⚠️</span>
          <div>
            <h3 className="text-sm font-bold">列表加载异常</h3>
            <p className="text-xs text-themeText-light mt-1">
              {(error as Error).message || '商户列表拉取失败，请检查网络连接或服务端口'}
            </p>
          </div>
          <button
            onClick={() => refetch()}
            className="px-5 py-2 text-xs font-bold text-white bg-primary hover:bg-primary-hover rounded-theme-md shadow-theme-sm"
          >
            重新加载
          </button>
        </div>
      )}

      {/* 4. 空状态展示 */}
      {!isLoading && !isError && (!merchants || merchants.length === 0) && (
        <div className="py-20 flex flex-col items-center justify-center text-center gap-3 bg-themeBg-card border border-themeBorder rounded-theme-lg">
          <span className="text-5xl">🔍</span>
          <h3 className="text-sm font-bold text-themeText-main">附近暂无推荐商户</h3>
          <p className="text-xs text-themeText-light max-w-xs">
            在该分类下未检索到符合条件的店铺，您可以试着更换分类或点击重新检索。
          </p>
        </div>
      )}

      {/* 5. 电脑桌面端响应式瀑布流/网格推荐列表 */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
        {isLoading
          ? // 加载中：循环输出 4 个骨架屏占位
            Array.from({ length: 8 }).map((_, idx) => <MerchantSkeleton key={idx} />)
          : // 加载完成：循环渲染真实卡片
            merchants?.map((merchant) => (
              <MerchantCard
                key={merchant.id}
                merchant={merchant}
                onClick={(id) => {
                  window.location.href = `/merchants/${id}`;
                }}
              />
            ))}
      </div>
    </div>
  );
}
