'use client';

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import { apiClient } from '../../../services/api-client';
import { MerchantDetail } from '../../../services/types';

// API 获取详情页数据
const fetchMerchantDetail = async (id: string): Promise<MerchantDetail> => {
  const response = await apiClient.get<MerchantDetail>(`/merchants/${id}`);
  return response;
};

export default function MerchantDetailPage() {
  const params = useParams();
  const id = params.id as string;

  // 1. 数据绑定与拉取
  const { data: detail, isLoading, isError, error } = useQuery<MerchantDetail>({
    queryKey: ['merchantDetail', id],
    queryFn: () => fetchMerchantDetail(id),
    enabled: !!id,
  });

  // 2. 状态控制：服务列表默认折叠前 2 项
  const [showAllServices, setShowAllServices] = useState<boolean>(false);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-8 animate-pulse">
        <div className="h-72 w-full rounded-theme-xl bg-themeBg-panel" />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          <div className="lg:col-span-2 flex flex-col gap-6">
            <div className="h-64 rounded-theme-lg bg-themeBg-panel" />
            <div className="h-96 rounded-theme-lg bg-themeBg-panel" />
          </div>
          <div className="h-80 rounded-theme-lg bg-themeBg-panel" />
        </div>
      </div>
    );
  }

  if (isError || !detail) {
    return (
      <div className="py-20 flex flex-col items-center justify-center gap-4 bg-themeBg-card border border-themeBorder rounded-theme-xl">
        <span className="text-4xl text-accent-red">❌</span>
        <h3 className="text-sm font-bold">商家详情加载异常</h3>
        <p className="text-xs text-themeText-light">
          {(error as Error)?.message || '无法获取商户的详细信息，请检查后台服务或网络状态'}
        </p>
        <button
          onClick={() => window.history.back()}
          className="px-5 py-2 text-xs font-bold text-themeText-muted bg-themeBg-card border border-themeBorder rounded-theme-md hover:bg-themeBg-panel"
        >
          返回上一页
        </button>
      </div>
    );
  }

  const displayedServices = showAllServices 
    ? detail.services 
    : detail.services.slice(0, 2);

  return (
    <div className="flex flex-col gap-8">
      {/* 1. 顶部宽屏 Hero 视觉横幅 (带透明毛玻璃浮层) */}
      <div className="relative h-72 w-full bg-themeBg-panel rounded-theme-xl overflow-hidden border border-themeBorder">
        <img
          src={detail.coverImage}
          alt={detail.name}
          className="h-full w-full object-cover"
        />
        {/* 返回按钮 */}
        <button
          onClick={() => window.history.back()}
          className="absolute left-6 top-6 flex items-center justify-center h-10 w-10 rounded-full bg-black/40 text-white backdrop-blur-md hover:bg-black/60 transition-colors"
        >
          ←
        </button>
        
        {/* 商户基本信息浮动卡片 - 融入 OAG 现代极简设计 */}
        <div className="absolute left-6 right-6 bottom-6 p-6 rounded-theme-lg bg-black/40 text-white border border-white/10 backdrop-blur-md flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <span className="inline-block px-2.5 py-0.5 rounded-theme-sm text-[9px] font-extrabold uppercase bg-white/20 text-white border border-white/10 tracking-wider mb-2">
              {detail.category}
            </span>
            <h1 className="text-2xl font-black tracking-tight leading-tight">{detail.name}</h1>
            <p className="text-xs text-white/80 mt-1">📍 {detail.address}</p>
          </div>
          <div className="flex items-center gap-3 sm:self-end">
            <span className="text-xs font-bold px-3 py-1.5 rounded-theme-md bg-white/20 border border-white/10 text-white">
              🗺️ {detail.distanceKm.toFixed(1)} km 处
            </span>
          </div>
        </div>
      </div>

      {/* 2. 双栏式主内容布局区域 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 items-start">
        
        {/* 左栏（占 2/3）：团购列表与用户评价 */}
        <div className="lg:col-span-2 flex flex-col gap-8">
          
          {/* 在线特惠服务列表卡片 */}
          <section className="bg-themeBg-card border border-themeBorder rounded-theme-xl p-6 shadow-theme-sm flex flex-col gap-6">
            <div className="flex items-center justify-between border-b border-themeBorder pb-3">
              <h2 className="text-base font-extrabold text-themeText-main flex items-center gap-2">
                <span>🔥</span> 在线特惠服务
              </h2>
              <span className="text-xs text-themeText-light">
                在线抢购立享折扣
              </span>
            </div>
            
            {detail.services.length === 0 ? (
              <p className="text-sm text-themeText-light py-8 italic text-center">商户暂未发布特惠服务</p>
            ) : (
              <div className="flex flex-col gap-4">
                {displayedServices.map((service) => (
                  <div
                    key={service.id}
                    className="flex gap-4 p-4 rounded-theme-md border border-themeBorder hover:border-primary/20 hover:bg-themeBg-panel transition-all duration-200"
                  >
                    <img
                      src={service.coverImage}
                      alt={service.title}
                      className="h-20 w-20 object-cover rounded-theme-sm shrink-0 bg-themeBg-panel"
                    />
                    <div className="flex-1 flex flex-col justify-between min-w-0">
                      <div className="flex justify-between items-start gap-2">
                        <div>
                          <h3 className="text-sm font-extrabold text-themeText-main truncate">{service.title}</h3>
                          <p className="text-[10px] text-themeText-light mt-1">已售 {service.soldCount} 件</p>
                        </div>
                        {service.tag && (
                          <span className="shrink-0 text-[9px] px-2 py-0.5 rounded-theme-sm font-extrabold text-white bg-secondary">
                            {service.tag}
                          </span>
                        )}
                      </div>
                      <div className="flex justify-between items-end mt-2">
                        <div className="flex items-baseline gap-2">
                          <span className="text-lg font-black text-primary">¥{service.currentPrice}</span>
                          <span className="text-xs line-through text-themeText-light">¥{service.originalPrice}</span>
                        </div>
                        <button className="px-5 py-2 text-xs font-bold text-white bg-primary hover:bg-primary-hover rounded-theme-md shadow-theme-sm active:scale-95 transition-transform">
                          立即抢购
                        </button>
                      </div>
                    </div>
                  </div>
                ))}

                {/* 折叠展开按钮 */}
                {detail.services.length > 2 && (
                  <button
                    onClick={() => setShowAllServices(!showAllServices)}
                    className="py-3 text-center text-xs font-extrabold text-primary border border-dashed border-primary/20 rounded-theme-md hover:bg-primary-light transition-all"
                  >
                    {showAllServices ? '折叠部分服务 ▴' : `展开全部 ${detail.services.length} 个特惠服务 ▾`}
                  </button>
                )}
              </div>
            )}
          </section>

          {/* 用户精选评价区域 */}
          <section className="bg-themeBg-card border border-themeBorder rounded-theme-xl p-6 shadow-theme-sm flex flex-col gap-6">
            <div className="flex items-center justify-between border-b border-themeBorder pb-3">
              <h2 className="text-base font-extrabold text-themeText-main flex items-center gap-2">
                <span>💬</span> 用户精选评价 ({detail.comments.length})
              </h2>
              <button className="px-3 py-1.5 rounded-theme-md text-xs font-bold text-primary hover:bg-primary-light transition-colors">
                + 发表评价
              </button>
            </div>

            {detail.comments.length === 0 ? (
              <p className="text-sm text-themeText-light py-12 italic text-center">暂无用户发表评价，期待你的第一条评价</p>
            ) : (
              <div className="flex flex-col gap-6">
                {detail.comments.map((comment) => (
                  <div 
                    key={comment.id} 
                    className="flex flex-col gap-3 pb-6 border-b border-themeBorder last:border-none last:pb-0"
                  >
                    {/* 用户头像及核心属性栏 */}
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <img
                          src={comment.avatarUrl}
                          alt={comment.username}
                          className="h-9 w-9 rounded-full object-cover bg-themeBg-panel"
                        />
                        <div>
                          <h4 className="text-xs font-bold text-themeText-main">{comment.username}</h4>
                          <div className="flex text-[10px] text-amber-400 mt-0.5">
                            {Array.from({ length: 5 }).map((_, i) => (
                              <span key={i} className="text-xs leading-none">
                                {i < comment.rating ? '★' : '☆'}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>
                      <span className="text-[10px] text-themeText-light font-medium">{comment.publishDate}</span>
                    </div>
                    
                    {/* 评价文字内容 */}
                    <p className="text-xs leading-relaxed text-themeText-muted px-1">
                      {comment.content}
                    </p>

                    {/* 评价配图 (横向滑动缩略图) */}
                    {comment.images && comment.images.length > 0 && (
                      <div className="flex gap-2 overflow-x-auto py-1 scrollbar-none px-1">
                        {comment.images.map((imgUrl, i) => (
                          <img
                            key={i}
                            src={imgUrl}
                            alt="用户晒图"
                            className="h-16 w-16 object-cover rounded-theme-sm shrink-0 border border-themeBorder hover:scale-102 transition-transform cursor-pointer"
                          />
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

        </div>

        {/* 右栏（占 1/3）：商户详细属性卡片 */}
        <div className="flex flex-col gap-6 lg:sticky lg:top-24">
          <section className="bg-themeBg-card border border-themeBorder rounded-theme-xl p-6 shadow-theme-sm flex flex-col gap-6">
            <h3 className="text-sm font-extrabold text-themeText-main border-b border-themeBorder pb-3">
              📝 商户基本资料
            </h3>
            
            <div className="flex flex-col gap-4 text-xs">
              {/* 评分评分展示 */}
              <div className="flex items-center justify-between p-3 rounded-theme-md bg-themeBg-panel border border-themeBorder">
                <span className="font-bold text-themeText-muted">综合星级</span>
                <div className="flex items-center gap-1.5">
                  <span className="text-amber-400 text-sm">★</span>
                  <span className="font-black text-sm text-themeText-main">{detail.rating.toFixed(1)}</span>
                  <span className="text-themeText-light">({detail.commentCount}条点评)</span>
                </div>
              </div>

              {/* 人均价格属性 */}
              <div className="flex items-center justify-between p-3 rounded-theme-md bg-themeBg-panel border border-themeBorder">
                <span className="font-bold text-themeText-muted">人均消费</span>
                <span className="font-extrabold text-themeText-main">¥ {detail.avgPrice}</span>
              </div>

              {/* 营业时间状态 */}
              <div className="flex flex-col gap-1.5 p-3 rounded-theme-md bg-themeBg-panel border border-themeBorder">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-themeText-muted">营业状态</span>
                  <span className="font-extrabold text-accent-green bg-accent-green/10 px-2 py-0.5 rounded-theme-sm text-[10px]">
                    营业中
                  </span>
                </div>
                <p className="text-[10px] text-themeText-light mt-1">服务时段: {detail.openTime}</p>
              </div>

              {/* 商家详细标签展现 */}
              <div className="flex flex-col gap-2">
                <span className="font-bold text-themeText-muted">商家标签</span>
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {detail.tags.map((tag, idx) => (
                    <span
                      key={idx}
                      className="text-[10px] font-bold px-2.5 py-1 rounded-theme-sm border text-themeText-muted border-themeBorder bg-themeBg-panel"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            </div>
            
            {/* 核心操作按钮 */}
            <div className="flex flex-col gap-2 border-t border-themeBorder pt-4">
              <button className="w-full py-3 rounded-theme-md text-xs font-bold text-white bg-primary hover:bg-primary-hover shadow-theme-sm transition-colors text-center">
                💬 呼叫 AI 代理对比此店
              </button>
              <button className="w-full py-3 rounded-theme-md text-xs font-bold text-themeText-muted bg-themeBg-panel border border-themeBorder hover:bg-themeBg-card transition-colors text-center">
                📞 联系商家咨询
              </button>
            </div>
          </section>
        </div>

      </div>
    </div>
  );
}
