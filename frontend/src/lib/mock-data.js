function createPoster(label, colors = ['#0f172a', '#0891b2', '#10b981']) {
  const text = String(label || '本地生活助手').slice(0, 12);
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 420">
      <defs>
        <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="${colors[0]}"/>
          <stop offset="55%" stop-color="${colors[1]}"/>
          <stop offset="100%" stop-color="${colors[2]}"/>
        </linearGradient>
      </defs>
      <rect width="720" height="420" rx="32" fill="url(#g)"/>
      <circle cx="610" cy="92" r="120" fill="rgba(255,255,255,0.08)"/>
      <circle cx="116" cy="330" r="150" fill="rgba(255,255,255,0.08)"/>
      <text x="58" y="132" fill="rgba(255,255,255,0.95)" font-size="52" font-family="PingFang SC, Microsoft YaHei, sans-serif" font-weight="700">${text}</text>
      <text x="58" y="192" fill="rgba(255,255,255,0.78)" font-size="24" font-family="PingFang SC, Microsoft YaHei, sans-serif">${text.length > 10 ? '本地服务样张' : '城市服务样张'}</text>
    </svg>
  `;

  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}

export const mockShopTypes = [
  { id: 1, name: '火锅', icon: '锅', sort: 1, summary: '热辣、围炉、社交感' },
  { id: 2, name: '烧烤', icon: '烤', sort: 2, summary: '夜宵和聚会首选' },
  { id: 3, name: '咖啡', icon: '咖', sort: 3, summary: '工作和休憩切换' },
  { id: 4, name: '甜品', icon: '甜', sort: 4, summary: '饭后和下午茶' },
  { id: 5, name: '日料', icon: '日', sort: 5, summary: '精致、清爽、安静' },
  { id: 6, name: '本帮菜', icon: '本', sort: 6, summary: '有烟火气的熟悉味道' },
];

export const mockShops = [
  {
    id: 101,
    typeId: 1,
    name: '沸腾江湖·鲜辣火锅',
    area: '徐汇',
    address: '虹桥路 188 号 2 层',
    avgPrice: 88,
    sold: 4310,
    comments: 862,
    score: 48,
    openHours: '10:00-22:30',
    distance: 0.7,
    images: createPoster('沸腾江湖', ['#0f172a', '#0891b2', '#14b8a6']),
    tags: ['招牌毛肚', '牛油锅底', '夜宵友好'],
  },
  {
    id: 102,
    typeId: 1,
    name: '山城一锅·微麻微辣',
    area: '静安',
    address: '南京西路 268 号',
    avgPrice: 96,
    sold: 2860,
    comments: 402,
    score: 46,
    openHours: '11:00-23:00',
    distance: 1.4,
    images: createPoster('山城一锅', ['#172554', '#0f766e', '#14b8a6']),
    tags: ['手切鲜牛肉', '鸳鸯锅', '适合聚会'],
  },
  {
    id: 103,
    typeId: 2,
    name: '烟火烤场·炭火烤串',
    area: '黄浦',
    address: '人民广场西侧地下 1 层',
    avgPrice: 68,
    sold: 5221,
    comments: 1002,
    score: 47,
    openHours: '17:00-02:00',
    distance: 0.4,
    images: createPoster('烟火烤场', ['#111827', '#7c2d12', '#f97316']),
    tags: ['深夜档', '冰镇啤酒', '炭火现烤'],
  },
  {
    id: 104,
    typeId: 3,
    name: '半刻咖啡·工作站',
    area: '浦东',
    address: '世纪大道 100 号',
    avgPrice: 42,
    sold: 1812,
    comments: 266,
    score: 49,
    openHours: '08:00-22:00',
    distance: 1.9,
    images: createPoster('半刻咖啡', ['#0f172a', '#1d4ed8', '#22d3ee']),
    tags: ['手冲', '轻食', '插座多'],
  },
  {
    id: 105,
    typeId: 4,
    name: '云朵甜品·夜色橱窗',
    area: '长宁',
    address: '延安西路 66 号',
    avgPrice: 36,
    sold: 940,
    comments: 158,
    score: 45,
    openHours: '12:00-22:00',
    distance: 2.3,
    images: createPoster('云朵甜品', ['#312e81', '#8b5cf6', '#f472b6']),
    tags: ['草莓蛋糕', '冰饮', '拍照好看'],
  },
  {
    id: 106,
    typeId: 5,
    name: '鱼町日料·极简餐桌',
    area: '闵行',
    address: '漕宝路 888 号',
    avgPrice: 128,
    sold: 1640,
    comments: 284,
    score: 49,
    openHours: '11:30-21:30',
    distance: 3.1,
    images: createPoster('鱼町日料', ['#111827', '#0f766e', '#22c55e']),
    tags: ['刺身拼盘', '午市套餐', '安静约会'],
  },
  {
    id: 107,
    typeId: 6,
    name: '老城厢·本帮小馆',
    area: '普陀',
    address: '长寿路 520 号',
    avgPrice: 72,
    sold: 2987,
    comments: 618,
    score: 44,
    openHours: '10:30-21:00',
    distance: 1.1,
    images: createPoster('老城厢', ['#1f2937', '#ea580c', '#f59e0b']),
    tags: ['红烧肉', '葱油拌面', '老上海味道'],
  },
  {
    id: 108,
    typeId: 2,
    name: '卷卷烤肉·社交夜场',
    area: '徐汇',
    address: '龙华中路 399 号',
    avgPrice: 112,
    sold: 2420,
    comments: 516,
    score: 48,
    openHours: '17:00-01:30',
    distance: 1.7,
    images: createPoster('卷卷烤肉', ['#111827', '#be123c', '#fb7185']),
    tags: ['韩式烤肉', '小菜多', '适合朋友聚餐'],
  },
];

export const mockBlogs = [
  {
    id: 201,
    shopId: 101,
    title: '本周值得去的火锅店，汤底、锅气和服务都在线',
    content: '这家店的牛油锅底很稳，鸭血和黄喉都很新鲜。晚高峰建议提前 30 分钟到店，AI 推荐的优惠券也很值得领。',
    liked: 328,
    comments: 46,
    images: createPoster('火锅探店', ['#0f172a', '#be123c', '#f97316']),
    name: '本地生活助手',
    icon: 'A',
    isLike: false,
    summary: '牛油锅底、鸭血、黄喉都在线，适合下班后聚餐。',
  },
  {
    id: 202,
    shopId: 104,
    title: '咖啡店的安静工作流：插座、座位和光线',
    content: '如果你需要一个半天都不想换地方的工作站，这家店很合适。窗口位比较抢手，午后阳光最好。',
    liked: 246,
    comments: 31,
    images: createPoster('咖啡工作站', ['#0f172a', '#1d4ed8', '#38bdf8']),
    name: '咖啡研究员',
    icon: 'C',
    isLike: true,
    summary: '适合办公和轻度会客，座位和光线都很稳定。',
  },
  {
    id: 203,
    shopId: 103,
    title: '深夜烤串地图：啤酒、碳香和社交氛围',
    content: '夜宵的快乐主要来自碳火香气和上菜速度，这家店都很能打。适合三五好友随时开局。',
    liked: 412,
    comments: 67,
    images: createPoster('烤串夜宵', ['#111827', '#ea580c', '#f59e0b']),
    name: '夜宵观察家',
    icon: 'N',
    isLike: false,
    summary: '深夜场稳定、上菜快、适合朋友局。',
  },
  {
    id: 204,
    shopId: 105,
    title: '甜品店拍照指南：要吃也要拍得好看',
    content: '这家店很适合下午茶，建议点草莓蛋糕和冰饮，橱窗位的背景最出片。',
    liked: 168,
    comments: 23,
    images: createPoster('甜品下午茶', ['#312e81', '#8b5cf6', '#f472b6']),
    name: '糖分选手',
    icon: 'S',
    isLike: false,
    summary: '拍照氛围感强，下午茶体验不错。',
  },
  {
    id: 205,
    shopId: 106,
    title: '日料小店的午市套餐为什么更适合第一次去',
    content: '午市套餐价格比较稳，出餐也更快。初次尝试的话，先从刺身拼盘和盖饭组合开始。',
    liked: 204,
    comments: 28,
    images: createPoster('日料午市', ['#111827', '#0f766e', '#22c55e']),
    name: '料理笔记',
    icon: 'R',
    isLike: true,
    summary: '午市套餐性价比高，适合初次尝试。',
  },
  {
    id: 206,
    shopId: 107,
    title: '本帮菜怎么点更稳：先看红烧肉和葱油拌面',
    content: '这家店的口味偏稳，适合带长辈或做一次本地口味复习。店员推荐的红烧肉火候很足。',
    liked: 175,
    comments: 20,
    images: createPoster('本帮小馆', ['#1f2937', '#ea580c', '#f59e0b']),
    name: '本地食记',
    icon: 'B',
    isLike: false,
    summary: '稳扎稳打的本帮菜，适合家庭场景。',
  },
];

export const mockVouchersByShopId = {
  101: [
    {
      id: 301,
      shopId: 101,
      shopName: '沸腾江湖·鲜辣火锅',
      title: '88 元代 100 元',
      subTitle: '午晚市通用，适合双人聚餐',
      payValue: 88,
      actualValue: 100,
      stock: 112,
      beginTime: '2026-05-01 10:00:00',
      endTime: '2026-06-30 22:00:00',
      rules: '仅限到店堂食使用，不与其他活动叠加',
    },
    {
      id: 302,
      shopId: 101,
      shopName: '沸腾江湖·鲜辣火锅',
      title: '秒杀双人锅底券',
      subTitle: '限量 50 张，适合下班后冲一波',
      payValue: 59,
      actualValue: 88,
      stock: 26,
      beginTime: '2026-05-01 18:00:00',
      endTime: '2026-05-31 23:59:59',
      rules: '每人限领一张，需提前预约',
    },
  ],
  104: [
    {
      id: 303,
      shopId: 104,
      shopName: '半刻咖啡·工作站',
      title: '38 元代 50 元',
      subTitle: '午后工作流友好，支持多次使用',
      payValue: 38,
      actualValue: 50,
      stock: 84,
      beginTime: '2026-05-01 09:00:00',
      endTime: '2026-06-15 20:00:00',
      rules: '满 50 元可用，咖啡和轻食均可',
    },
  ],
};

export const mockUserProfile = {
  id: 9001,
  nickName: '本地生活助手游客',
  icon: 'G',
  level: '服务体验官',
  city: '上海',
  bio: '现在直接进入服务大厅，先看店、再看券、最后交给 AI。',
};

export const mockMeStats = {
  signStreak: 6,
  favoriteCount: 18,
  visitCount: 42,
  followingCount: 7,
};

export const mockAssistantSessions = [
  {
    id: 'sess-001',
    title: '推荐火锅券',
    page: 'ai',
    topic: '火锅',
    createdAt: '2026-05-13T08:00:00.000Z',
    updatedAt: '2026-05-13T08:12:00.000Z',
    context: { page: 'shops', typeName: '火锅', shopName: '沸腾江湖·鲜辣火锅' },
    messages: [
      { id: 'm1', role: 'user', content: '推荐附近火锅', createdAt: '2026-05-13T08:00:00.000Z' },
      { id: 'm2', role: 'assistant', content: '我先给你筛了一批火锅店。你可以继续让我看优惠券或对比同类店。', createdAt: '2026-05-13T08:00:04.000Z' },
    ],
  },
  {
    id: 'sess-002',
    title: '咖啡工作站',
    page: 'ai',
    topic: '咖啡',
    createdAt: '2026-05-13T12:30:00.000Z',
    updatedAt: '2026-05-13T12:36:00.000Z',
    context: { page: 'shops', typeName: '咖啡', shopName: '半刻咖啡·工作站' },
    messages: [
      { id: 'm1', role: 'user', content: '帮我找一个适合写代码的咖啡店', createdAt: '2026-05-13T12:30:00.000Z' },
      { id: 'm2', role: 'assistant', content: '我会优先看插座、座位密度和光线。', createdAt: '2026-05-13T12:30:05.000Z' },
    ],
  },
];

export function getMockShopTypeById(typeId) {
  return mockShopTypes.find((item) => item.id === Number(typeId));
}

export function getMockShopById(id) {
  return mockShops.find((item) => item.id === Number(id));
}

export function getMockBlogById(id) {
  return mockBlogs.find((item) => item.id === Number(id));
}

export function getMockVouchersByShopId(shopId) {
  return mockVouchersByShopId[Number(shopId)] || [];
}

export function searchMockShops(query) {
  const normalized = String(query || '').trim().toLowerCase();
  if (!normalized) {
    return [...mockShops];
  }

  return mockShops.filter((shop) => {
    const haystack = [
      shop.name,
      shop.area,
      shop.address,
      ...(shop.tags || []),
    ]
      .join(' ')
      .toLowerCase();
    return haystack.includes(normalized);
  });
}

export function filterMockShopsByType(typeId, query = '') {
  const normalizedType = Number(typeId);
  const baseList = normalizedType ? mockShops.filter((shop) => shop.typeId === normalizedType) : [...mockShops];
  const normalizedQuery = String(query || '').trim().toLowerCase();
  if (!normalizedQuery) {
    return baseList;
  }

  return baseList.filter((shop) => {
    const haystack = [shop.name, shop.area, shop.address, ...(shop.tags || [])].join(' ').toLowerCase();
    return haystack.includes(normalizedQuery);
  });
}
