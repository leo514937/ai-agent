export function buildNavItems() {
  return [
    { path: '/', label: '本地生活助手', hint: '服务总览', glyph: '⌂', tone: 'cyan' },
    { path: '/shops', label: '商铺', hint: '分类 / 详情 / 优惠券', glyph: '◫', tone: 'amber' },
    { path: '/blogs', label: '博客', hint: '热门 / 关注 / 点赞', glyph: '✎', tone: 'violet' },
    { path: '/ai', label: 'AI 助手', hint: '推荐 / 对比 / 讲解', glyph: '⚡', tone: 'emerald' },
    { path: '/me', label: '我的', hint: '个人中心 / 签到', glyph: '◉', tone: 'slate' },
  ];
}

export function resolveRouteTitle(pathname) {
  if (/^\/shops\/\d+/.test(pathname)) return '商铺详情';
  if (/^\/blogs\/\d+/.test(pathname)) return '博客详情';
  if (pathname === '/shops') return '商铺';
  if (pathname === '/blogs') return '博客';
  if (pathname === '/ai') return 'AI 助手';
  if (pathname === '/me') return '个人中心';
  return '首页';
}

export function resolveRouteSubtitle(pathname) {
  if (pathname === '/shops') return '按分类、距离和价格浏览附近店铺';
  if (pathname === '/blogs') return '查看热度、口碑和探店笔记';
  if (pathname === '/ai') return '让 AI 帮你挑店、看券、做对比';
  if (pathname === '/me') return '查看你的个人状态和服务记录';
  return '本地生活助手用户服务大厅';
}
