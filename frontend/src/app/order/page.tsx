'use client';

import React from 'react';

interface MockOrder {
  id: string;
  shopName: string;
  voucherTitle: string;
  payPrice: number;
  actualPrice: number;
  status: 'UNPAID' | 'PAID' | 'USED' | 'CANCELLED' | 'REFUNDED';
  date: string;
}

export default function OrderPage() {
  const orders: MockOrder[] = [
    {
      id: '16834920485910',
      shopName: '103茶餐厅',
      voucherTitle: '100元代金券',
      payPrice: 80,
      actualPrice: 100,
      status: 'PAID',
      date: '2026-06-23 12:30:15',
    },
    {
      id: '16834918239401',
      shopName: '海底捞火锅(水晶城店)',
      voucherTitle: '50元立减代金券',
      payPrice: 40,
      actualPrice: 50,
      status: 'USED',
      date: '2026-06-22 19:15:00',
    },
    {
      id: '16834900591024',
      shopName: '星剪造型·发型工作室',
      voucherTitle: '平日洗剪吹设计套餐券',
      payPrice: 168,
      actualPrice: 218,
      status: 'UNPAID',
      date: '2026-06-21 10:00:20',
    },
    {
      id: '16834892019485',
      shopName: '蔡馬洪涛烤肉·老北京铜锅涮羊肉',
      voucherTitle: '双人特惠超值套餐',
      payPrice: 238,
      actualPrice: 298,
      status: 'REFUNDED',
      date: '2026-06-18 18:20:45',
    },
  ];

  const getStatusStyle = (status: MockOrder['status']) => {
    switch (status) {
      case 'UNPAID':
        return 'text-amber-500 bg-amber-500/10 border-amber-500/20';
      case 'PAID':
        return 'text-green-500 bg-green-500/10 border-green-500/20';
      case 'USED':
        return 'text-themeText-light bg-themeBg-panel border-themeBorder';
      case 'CANCELLED':
        return 'text-themeText-light bg-themeBg-panel border-themeBorder line-through';
      case 'REFUNDED':
        return 'text-accent-red bg-accent-red/10 border-accent-red/20';
      default:
        return '';
    }
  };

  const getStatusText = (status: MockOrder['status']) => {
    switch (status) {
      case 'UNPAID':
        return '待付款';
      case 'PAID':
        return '已付款 (待消费)';
      case 'USED':
        return '已消费';
      case 'CANCELLED':
        return '已取消';
      case 'REFUNDED':
        return '已退款';
      default:
        return '未知状态';
    }
  };

  return (
    <div className="flex flex-col gap-8">
      {/* Page Header */}
      <div className="flex items-center justify-between border-b border-themeBorder pb-5">
        <h2 className="font-extrabold text-lg text-themeText-main">我的抢购订单</h2>
        <span className="text-xs text-themeText-light">
          当前共 {orders.length} 笔订单
        </span>
      </div>

      {/* Orders List */}
      <div className="flex flex-col gap-5">
        {orders.map((order) => (
          <div
            key={order.id}
            className="bg-themeBg-card border border-themeBorder rounded-theme-xl p-6 shadow-theme-sm flex flex-col sm:flex-row justify-between gap-6"
          >
            {/* 左侧订单信息 */}
            <div className="flex flex-col gap-3">
              <div className="flex items-center gap-3">
                <span className="font-extrabold text-sm text-themeText-main">{order.shopName}</span>
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${getStatusStyle(order.status)}`}>
                  {getStatusText(order.status)}
                </span>
              </div>
              <div className="text-xs text-themeText-muted font-bold flex flex-col gap-1">
                <p>🎫 团购券：{order.voucherTitle}</p>
                <p className="text-[10px] text-themeText-light font-medium">订单编号：{order.id}</p>
                <p className="text-[10px] text-themeText-light font-medium">下单时间：{order.date}</p>
              </div>
            </div>

            {/* 右侧价格与操作 */}
            <div className="flex flex-col justify-between items-end gap-4 min-w-[120px] self-end sm:self-stretch">
              <div className="text-right">
                <p className="text-xs text-themeText-light">实付金额</p>
                <div className="flex items-baseline gap-1.5 justify-end mt-1">
                  <span className="text-lg font-black text-primary">¥{order.payPrice}</span>
                  <span className="text-[10px] line-through text-themeText-light">¥{order.actualPrice}</span>
                </div>
              </div>

              <div className="flex gap-2">
                {order.status === 'UNPAID' && (
                  <>
                    <button className="px-4 py-2 rounded-theme-md text-xs font-bold text-white bg-primary hover:bg-primary-hover shadow-theme-sm transition-all active:scale-95">
                      立即支付
                    </button>
                    <button className="px-4 py-2 rounded-theme-md text-xs font-bold text-themeText-muted bg-themeBg-panel border border-themeBorder hover:bg-themeBg-card transition-all active:scale-95">
                      取消订单
                    </button>
                  </>
                )}
                {order.status === 'PAID' && (
                  <>
                    <button className="px-4 py-2 rounded-theme-md text-xs font-bold text-white bg-secondary hover:bg-secondary-hover shadow-theme-sm transition-all active:scale-95">
                      查看券码
                    </button>
                    <button className="px-4 py-2 rounded-theme-md text-xs font-bold text-themeText-muted bg-themeBg-panel border border-themeBorder hover:bg-themeBg-card transition-all active:scale-95">
                      申请退款
                    </button>
                  </>
                )}
                {(order.status === 'USED' || order.status === 'REFUNDED') && (
                  <button className="px-4 py-2 rounded-theme-md text-xs font-bold text-themeText-muted bg-themeBg-panel border border-themeBorder hover:bg-themeBg-card transition-all active:scale-95">
                    再次抢购
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
