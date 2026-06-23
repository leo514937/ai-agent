/**
 * 统一 API 响应包装结构
 */
export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
}

/**
 * 优惠券/到店服务项定义
 */
export interface MerchantService {
  id: string;
  merchantId: string;
  title: string;
  coverImage: string;
  originalPrice: number;    // 原价
  currentPrice: number;     // 团购价/现价
  soldCount: number;        // 已售数量
  tag?: string;             // 如 "精选", "随时退"
  description?: string;     // 详细介绍
}

/**
 * 用户评价定义
 */
export interface MerchantComment {
  id: string;
  userId: string;
  username: string;
  avatarUrl: string;
  rating: number;           // 评分 (1-5)
  publishDate: string;      // 评价时间
  content: string;          // 评价文本
  images?: string[];        // 用户上传的图片
}

/**
 * 商户核心实体接口定义
 */
export interface Merchant {
  id: string;
  name: string;
  coverImage: string;
  rating: number;           // 评分 (0.0-5.0)
  commentCount: number;     // 评价数
  avgPrice: number;         // 人均消费
  category: string;         // 分类 (如: 火锅, 按摩, 汽车美容)
  subCategory?: string;     // 二级分类
  address: string;
  distanceKm: number;       // 与当前用户的距离 (km)
  latitude: number;
  longitude: number;
  openTime: string;         // 营业时间 (如 "09:00-22:00")
  tags: string[];           // 标签 (如 "免预约", "免费停车")
  hasCoupon: boolean;       // 是否有券
  couponTip?: string;       // 优惠券最强优惠描述 (如 "100元代金券85折")
}

/**
 * 详情页商户完整视图接口定义 (包含服务列表和评价)
 */
export interface MerchantDetail extends Merchant {
  services: MerchantService[];
  comments: MerchantComment[];
}
