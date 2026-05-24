package com.hmdp.ai.query;

/**
 * AI 读数据路由类型，保留给主线程做意图分发。
 */
public enum AiRouteType {
    RECOMMEND,
    COMPARE,
    VOUCHER,
    DETAIL,
    FAQ
}
