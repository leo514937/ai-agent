package com.hmdp.service;

import com.hmdp.ai.query.AiBusinessQueryFacade;
import com.hmdp.ai.query.AiQueryContext;
import com.hmdp.ai.query.dto.AiShopDetailDigest;
import com.hmdp.dto.ai.internal.AiInternalOrderStateResponse;
import com.hmdp.dto.ai.internal.AiInternalShopSearchRequest;
import com.hmdp.dto.ai.internal.AiInternalShopSearchResponse;
import com.hmdp.dto.ai.internal.AiInternalShopBlogListResponse;
import com.hmdp.entity.Blog;
import com.hmdp.entity.Shop;
import com.hmdp.entity.VoucherOrder;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Collections;
import java.util.HashMap;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AiInternalBusinessServiceTest {

    @Test
    void shouldReturnNoResultWhenOrderMissing() {
        AiBusinessQueryFacade queryFacade = mock(AiBusinessQueryFacade.class);
        IVoucherOrderService voucherOrderService = mock(IVoucherOrderService.class);

        AiInternalBusinessService service = new AiInternalBusinessService();
        ReflectionTestUtils.setField(service, "aiBusinessQueryFacade", queryFacade);
        ReflectionTestUtils.setField(service, "voucherOrderService", voucherOrderService);

        when(voucherOrderService.getById(404L)).thenReturn(null);

        AiInternalOrderStateResponse response = service.getOrderState(404L);

        assertFalse(response.isFound());
        assertEquals("no_result", response.getCode());
        assertEquals("NO_RESULT", response.getStatus());
    }

    @Test
    void shouldSearchShopsThroughBusinessFacade() {
        AiBusinessQueryFacade queryFacade = mock(AiBusinessQueryFacade.class);
        IVoucherOrderService voucherOrderService = mock(IVoucherOrderService.class);

        AiInternalBusinessService service = new AiInternalBusinessService();
        ReflectionTestUtils.setField(service, "aiBusinessQueryFacade", queryFacade);
        ReflectionTestUtils.setField(service, "voucherOrderService", voucherOrderService);

        Shop shop = new Shop();
        shop.setId(1001L);
        shop.setName("示例火锅店");
        shop.setArea("西湖区");
        shop.setAddress("文三路");
        shop.setAvgPrice(88L);
        shop.setScore(47);
        shop.setComments(123);

        AiQueryContext queryContext = AiQueryContext.from(new HashMap<String, Object>(), null);
        when(queryFacade.resolveContext(any(), any())).thenReturn(queryContext);
        when(queryFacade.recommendCandidates(any(AiQueryContext.class), anyInt())).thenReturn(Collections.singletonList(shop));

        AiInternalShopSearchRequest request = new AiInternalShopSearchRequest();
        request.setMessage("推荐火锅");
        request.setLimit(3);

        AiInternalShopSearchResponse response = service.searchShops(request);

        assertEquals(1, response.getShops().size());
        assertEquals("示例火锅店", response.getShops().get(0).getName());
        assertTrue(response.getResolvedContext().containsKey("page"));
    }

    @Test
    void shouldMapExistingOrderStatus() {
        AiBusinessQueryFacade queryFacade = mock(AiBusinessQueryFacade.class);
        IVoucherOrderService voucherOrderService = mock(IVoucherOrderService.class);

        AiInternalBusinessService service = new AiInternalBusinessService();
        ReflectionTestUtils.setField(service, "aiBusinessQueryFacade", queryFacade);
        ReflectionTestUtils.setField(service, "voucherOrderService", voucherOrderService);

        VoucherOrder order = new VoucherOrder();
        order.setId(9001L);
        order.setVoucherId(3001L);
        order.setUserId(8L);
        order.setStatus(2);
        when(voucherOrderService.getById(9001L)).thenReturn(order);

        AiInternalOrderStateResponse response = service.getOrderState(9001L);

        assertTrue(response.isFound());
        assertEquals("ok", response.getCode());
        assertEquals("PAID", response.getStatus());
        assertEquals(3001L, response.getVoucherId());
    }

    @Test
    void shouldReturnShopBlogsThroughInternalApi() {
        AiBusinessQueryFacade queryFacade = mock(AiBusinessQueryFacade.class);
        IVoucherOrderService voucherOrderService = mock(IVoucherOrderService.class);

        AiInternalBusinessService service = new AiInternalBusinessService();
        ReflectionTestUtils.setField(service, "aiBusinessQueryFacade", queryFacade);
        ReflectionTestUtils.setField(service, "voucherOrderService", voucherOrderService);

        Blog blog = new Blog();
        blog.setId(701L);
        blog.setShopId(1001L);
        blog.setUserId(8L);
        blog.setTitle("家庭聚餐体验");
        blog.setContent("环境安静，长辈也觉得舒服。");
        blog.setLiked(18);

        Shop shop = new Shop();
        shop.setId(1001L);
        shop.setName("示例家常菜");

        AiShopDetailDigest digest = new AiShopDetailDigest();
        digest.setShop(shop);
        digest.setBlogs(Collections.singletonList(blog));

        AiQueryContext queryContext = AiQueryContext.from(new HashMap<String, Object>(), null);
        when(queryFacade.resolveContext(any(), any())).thenReturn(queryContext);
        when(queryFacade.buildShopDetailDigest(any(AiQueryContext.class), anyInt(), anyInt())).thenReturn(digest);

        AiInternalShopBlogListResponse response = service.listShopBlogs(1001L, 3);

        assertEquals(1001L, response.getShopId());
        assertEquals(1, response.getBlogs().size());
        assertEquals("家庭聚餐体验", response.getBlogs().get(0).getTitle());
    }
}
