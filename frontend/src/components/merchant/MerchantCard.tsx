import React from 'react';
import { Merchant } from '../../services/types';

interface MerchantCardProps {
  merchant: Merchant;
  onClick?: (id: string) => void;
}

export const MerchantCard: React.FC<MerchantCardProps> = ({ merchant, onClick }) => {
  const {
    id,
    name,
    coverImage,
    rating,
    commentCount,
    avgPrice,
    category,
    distanceKm,
    tags,
    hasCoupon,
    couponTip,
  } = merchant;

  return (
    <div
      onClick={() => onClick?.(id)}
      className="group relative flex flex-col overflow-hidden rounded-theme-lg border transition-all duration-300 ease-out cursor-pointer
        bg-themeBg-card border-themeBorder shadow-theme-sm hover:shadow-theme-md hover:-translate-y-1 hover:border-primary/30"
    >
      {/* 商户大图容器 */}
      <div className="relative aspect-[4/3] w-full overflow-hidden bg-themeBg-panel">
        <img
          src={coverImage}
          alt={name}
          loading="lazy"
          className="h-full w-full object-cover transition-transform duration-500 ease-out group-hover:scale-105"
        />
        {/* 品类分类标签 - 悬浮在图片上 */}
        <span className="absolute left-3 top-3 rounded-theme-sm px-2 py-0.5 text-[10px] font-bold backdrop-blur-md text-white bg-black/40">
          {category}
        </span>
        
        {/* 优惠券角标 - 高信噪比表现 */}
        {hasCoupon && (
          <div className="absolute right-3 top-3 flex items-center gap-1 rounded-theme-sm px-2 py-0.5 text-[10px] font-bold text-white bg-primary shadow-theme-sm">
            <span>券</span>
          </div>
        )}
      </div>

      {/* 文本内容区域 */}
      <div className="flex flex-1 flex-col p-4">
        {/* 商户名称 */}
        <h3 className="line-clamp-1 text-sm font-extrabold transition-colors duration-200 text-themeText-main group-hover:text-primary">
          {name}
        </h3>

        {/* 评分与评价数、价格行 */}
        <div className="mt-2 flex items-center justify-between text-xs">
          <div className="flex items-center gap-1.5">
            {/* 星星 Icon */}
            <svg
              className="h-3.5 w-3.5 text-amber-400"
              fill="currentColor"
              viewBox="0 0 20 20"
            >
              <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
            </svg>
            <span className="font-bold text-themeText-main">{rating.toFixed(1)}</span>
            <span className="text-[10px] text-themeText-light">({commentCount}条评价)</span>
          </div>
          <span className="font-bold text-themeText-muted text-[10px]">
            人均 ¥{avgPrice}
          </span>
        </div>

        {/* 标签列表 */}
        {tags && tags.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {tags.slice(0, 2).map((tag, idx) => (
              <span
                key={idx}
                className="rounded-theme-sm px-2 py-0.5 text-[9px] font-bold border text-themeText-muted border-themeBorder bg-themeBg-panel"
              >
                {tag}
              </span>
            ))}
          </div>
        )}

        {/* 分割线 */}
        <div className="my-3 border-t border-themeBorder" />

        {/* 优惠信息与距离的展示 */}
        <div className="mt-auto flex items-center justify-between text-[11px]">
          {/* 最强优惠券提示 */}
          <div className="flex items-center gap-1 min-w-0 flex-1">
            {hasCoupon && couponTip ? (
              <p className="truncate font-bold text-secondary flex items-center gap-1.5">
                <span className="inline-block scale-90 px-1 py-0.2 rounded border border-secondary text-[9px] font-extrabold bg-secondary/5">
                  惠
                </span>
                {couponTip}
              </p>
            ) : (
              <span className="text-themeText-light italic text-[10px]">暂无团购优惠</span>
            )}
          </div>
          
          {/* 距离 */}
          <span className="ml-2 font-bold shrink-0 text-themeText-light">
            {distanceKm < 1 ? `${(distanceKm * 1000).toFixed(0)}m` : `${distanceKm.toFixed(1)}km`}
          </span>
        </div>
      </div>
    </div>
  );
};

export default MerchantCard;
