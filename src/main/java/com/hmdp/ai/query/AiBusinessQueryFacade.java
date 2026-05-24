package com.hmdp.ai.query;

import com.hmdp.dto.UserDTO;
import com.hmdp.entity.Shop;
import com.hmdp.entity.Voucher;
import com.hmdp.ai.query.dto.AiCompareDigest;
import com.hmdp.ai.query.dto.AiReputationDigest;
import com.hmdp.ai.query.dto.AiShopDetailDigest;
import com.hmdp.ai.query.dto.AiUserContextDigest;

import java.util.List;
import java.util.Map;

/**
 * 点评业务只读查询适配层。
 *
 * 说明：
 * - 所有方法只读
 * - 主线程后续可以直接注入这个 facade，而不用碰底层 mapper
 * - 先把查询能力收敛成稳定接口，再由上层 AI 做意图分发
 */
public interface AiBusinessQueryFacade {

    AiQueryContext resolveContext(Map<String, Object> context, UserDTO currentUser);

    AiRouteType resolveRoute(String message, AiQueryContext context);

    List<Shop> recommendCandidates(AiQueryContext context, int limit);

    List<Voucher> listVouchers(AiQueryContext context, int limit);

    AiShopDetailDigest buildShopDetailDigest(AiQueryContext context, int voucherLimit, int blogLimit);

    AiCompareDigest buildCompareDigest(AiQueryContext context, int limit);

    AiReputationDigest buildReputationDigest(AiQueryContext context, int blogLimit, int commentLimit);

    AiUserContextDigest buildUserContextDigest(AiQueryContext context);
}
