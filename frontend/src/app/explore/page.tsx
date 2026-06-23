'use client';

import React from 'react';

export default function ExplorePage() {
  const hotTopics = [
    {
      title: '🔥 附近热门美食推荐',
      desc: '“附近有什么性价比高、评分又好的火锅推荐吗？”',
      query: '附近推荐火锅',
      color: 'from-amber-500/10 to-orange-500/10 border-orange-500/20 text-orange-600 dark:text-orange-400',
    },
    {
      title: '🎤 KTV对比与挑选',
      desc: '“帮我对比一下水晶城和远洋乐堤港的KTV，哪家有券且性价比最高？”',
      query: '对比附近的KTV',
      color: 'from-blue-500/10 to-indigo-500/10 border-blue-500/20 text-blue-600 dark:text-blue-400',
    },
    {
      title: '💆 到店SPA放松推荐',
      desc: '“工作累了，想在附近找个按摩推拿养生馆，要求有代金券并且离我最近的。”',
      query: '推荐附近的按摩SPA',
      color: 'from-teal-500/10 to-emerald-500/10 border-teal-500/20 text-teal-600 dark:text-teal-400',
    },
    {
      title: '💇 丽人美发与造型',
      desc: '“武林广场附近的星剪造型好不好？今天营业到几点？”',
      query: '星剪造型营业时间',
      color: 'from-pink-500/10 to-rose-500/10 border-pink-500/20 text-pink-600 dark:text-pink-400',
    },
  ];

  const handleTopicClick = (query: string) => {
    // 触发全局事件或向 Window 挂载的打开 chat 方法发送消息
    if (typeof window !== 'undefined') {
      const event = new CustomEvent('open-ai-chat', { detail: { query } });
      window.dispatchEvent(event);
    }
  };

  return (
    <div className="flex flex-col gap-8">
      {/* Hero Banner */}
      <section className="bg-gradient-to-r from-primary/10 via-secondary/5 to-transparent border border-themeBorder rounded-theme-xl p-8 relative overflow-hidden">
        <h2 className="font-extrabold text-2xl text-themeText-main tracking-tight mb-2">
          发现周边好店与智能 AI 导购
        </h2>
        <p className="text-xs text-themeText-muted max-w-2xl leading-relaxed">
          AI 助手已与大众点评核心库打通，您可以直接通过自然语言让 AI 帮您筛选、对比和查询商家的代金券活动。
        </p>
      </section>

      {/* 热门调优主题 */}
      <div>
        <h3 className="font-extrabold text-sm uppercase tracking-wider text-themeText-light mb-4">
          💡 热门 AI 对话话题
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {hotTopics.map((topic, index) => (
            <div
              key={index}
              onClick={() => handleTopicClick(topic.query)}
              className={`p-5 rounded-theme-lg border bg-gradient-to-br transition-all duration-300 cursor-pointer hover:scale-102 hover:shadow-theme-md flex flex-col justify-between gap-4 ${topic.color}`}
            >
              <div>
                <h4 className="font-extrabold text-sm mb-1">{topic.title}</h4>
                <p className="text-xs opacity-80 leading-relaxed italic">{topic.desc}</p>
              </div>
              <button className="self-end px-3 py-1.5 rounded-theme-sm text-[10px] font-bold text-white bg-primary hover:bg-primary-hover shadow-theme-sm transition-transform active:scale-95">
                咨询 AI ➔
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* 社区笔记发现 */}
      <div>
        <h3 className="font-extrabold text-sm uppercase tracking-wider text-themeText-light mb-4">
          📸 精选社区探店笔记
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          <div className="bg-themeBg-card border border-themeBorder rounded-theme-lg overflow-hidden shadow-theme-sm hover:shadow-theme-md transition-all duration-300">
            <div className="h-44 bg-themeBg-panel relative">
              <img
                src="https://qcloud.dpfile.com/pc/jiclIsCKmOI2arxKN1Uf0Hx3PucIJH8q0QSz-Z8llzcN56-_QiKuOvyio1OOxsRtFoXqu0G3iT2T27qat3WhLVEuLYk00OmSS1IdNpm8K8sG4JN9RIm2mTKcbLtc2o2vfCF2ubeXzk49OsGrXt_KYDCngOyCwZK-s3fqawWswzk.jpg"
                alt="美食"
                className="w-full h-full object-cover"
              />
            </div>
            <div className="p-4">
              <h4 className="font-extrabold text-xs text-themeText-main line-clamp-1">人均30💰 杭州这家港式茶餐厅我疯狂打call‼️</h4>
              <p className="text-[10px] text-themeText-muted mt-2 line-clamp-2 leading-relaxed">
                这碗黯然销魂饭我吹爆！米饭上盖满了甜甜的叉烧，还有两颗溏心蛋，每一粒米饭都裹着浓郁的酱汁，强烈推荐！
              </p>
              <div className="flex items-center justify-between mt-4 pt-3 border-t border-themeBorder text-[10px] text-themeText-light font-bold">
                <span>👤 可可今天不吃肉</span>
                <span>❤️ 1,024 赞</span>
              </div>
            </div>
          </div>

          <div className="bg-themeBg-card border border-themeBorder rounded-theme-lg overflow-hidden shadow-theme-sm hover:shadow-theme-md transition-all duration-300">
            <div className="h-44 bg-themeBg-panel relative">
              <img
                src="https://img.meituan.net/msmerchant/232f8fdf09050838bd33fb24e79f30f9606056.jpg"
                alt="美发"
                className="w-full h-full object-cover"
              />
            </div>
            <div className="p-4">
              <h4 className="font-extrabold text-xs text-themeText-main line-clamp-1">周末好去处丨浪漫的花园西餐厅打卡 🍷</h4>
              <p className="text-[10px] text-themeText-muted mt-2 line-clamp-2 leading-relaxed">
                超大一块战斧牛排经过火焰的炙烤发出阵阵香气，外焦里嫩。这是一家最最最美花园的西餐厅，到处都是鲜花，非常适合情侣约会。
              </p>
              <div className="flex items-center justify-between mt-4 pt-3 border-t border-themeBorder text-[10px] text-themeText-light font-bold">
                <span>👤 小鱼同学</span>
                <span>❤️ 785 赞</span>
              </div>
            </div>
          </div>

          <div className="bg-themeBg-card border border-themeBorder rounded-theme-lg overflow-hidden shadow-theme-sm hover:shadow-theme-md transition-all duration-300">
            <div className="h-44 bg-themeBg-panel relative">
              <img
                src="https://p0.meituan.net/dpmerchantpic/53e74b200211d68988a4f02ae9912c6c1076826.jpg"
                alt="休闲"
                className="w-full h-full object-cover"
              />
            </div>
            <div className="p-4">
              <h4 className="font-extrabold text-xs text-themeText-main line-clamp-1">放松充能丨钱江新城这家高端SPA氛围太赞了</h4>
              <p className="text-[10px] text-themeText-muted mt-2 line-clamp-2 leading-relaxed">
                周末过来放松一下，环境非常私密幽静，技师手法相当专业，做完肩颈按摩后整个人像重新活过来一样。
              </p>
              <div className="flex items-center justify-between mt-4 pt-3 border-t border-themeBorder text-[10px] text-themeText-light font-bold">
                <span>👤 爱生活，爱点评</span>
                <span>❤️ 620 赞</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
