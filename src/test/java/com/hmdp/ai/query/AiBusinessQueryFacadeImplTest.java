package com.hmdp.ai.query;

import com.hmdp.dto.UserDTO;
import com.hmdp.entity.Blog;
import com.hmdp.entity.Shop;
import com.hmdp.entity.ShopType;
import com.hmdp.service.IBlogCommentsService;
import com.hmdp.service.IBlogService;
import com.hmdp.service.IFollowService;
import com.hmdp.service.IShopService;
import com.hmdp.service.IShopTypeService;
import com.hmdp.service.IUserInfoService;
import com.hmdp.service.IUserService;
import com.hmdp.service.IVoucherService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AiBusinessQueryFacadeImplTest {

    private AiBusinessQueryFacadeImpl facade;
    private IShopService shopService;
    private IVoucherService voucherService;
    private IBlogService blogService;
    private IShopTypeService shopTypeService;
    private IUserService userService;
    private IUserInfoService userInfoService;
    private IFollowService followService;
    private IBlogCommentsService blogCommentsService;

    @BeforeEach
    void setUp() {
        facade = new AiBusinessQueryFacadeImpl();
        shopService = mock(IShopService.class);
        voucherService = mock(IVoucherService.class);
        blogService = mock(IBlogService.class);
        shopTypeService = mock(IShopTypeService.class);
        userService = mock(IUserService.class);
        userInfoService = mock(IUserInfoService.class);
        followService = mock(IFollowService.class);
        blogCommentsService = mock(IBlogCommentsService.class);

        ReflectionTestUtils.setField(facade, "shopService", shopService);
        ReflectionTestUtils.setField(facade, "voucherService", voucherService);
        ReflectionTestUtils.setField(facade, "blogService", blogService);
        ReflectionTestUtils.setField(facade, "shopTypeService", shopTypeService);
        ReflectionTestUtils.setField(facade, "userService", userService);
        ReflectionTestUtils.setField(facade, "userInfoService", userInfoService);
        ReflectionTestUtils.setField(facade, "followService", followService);
        ReflectionTestUtils.setField(facade, "blogCommentsService", blogCommentsService);
    }

    @Test
    void resolveContextShouldPromoteAnchorShopAndConstraintCategory() {
        Map<String, Object> context = new HashMap<>();
        context.put("current_shop_anchor", linkedMap(
                "shop_id", 9L,
                "shop_name", "海底捞水晶城店"
        ));
        context.put("current_constraints", linkedMap("category", "火锅"));
        context.put("follow_up_kind", "entity_reference");
        context.put("needs_clarification", false);

        UserDTO user = new UserDTO();
        user.setId(1L);
        user.setNickName("小明");

        Shop shop = new Shop();
        shop.setId(9L);
        shop.setName("海底捞水晶城店");
        shop.setTypeId(3L);

        ShopType type = new ShopType();
        type.setId(3L);
        type.setName("火锅");

        when(shopService.getById(9L)).thenReturn(shop);
        when(shopTypeService.getById(3L)).thenReturn(type);

        AiQueryContext resolved = facade.resolveContext(context, user);

        assertEquals(Long.valueOf(9L), resolved.getShopId());
        assertEquals("海底捞水晶城店", resolved.getShopName());
        assertEquals(Long.valueOf(3L), resolved.getTypeId());
        assertEquals("火锅", resolved.getTypeName());
        assertEquals(Long.valueOf(1L), resolved.getUserId());
        assertEquals("小明", resolved.getUserNickName());
        assertFalse(resolved.getRawContext().isEmpty());
        assertNotNull(resolved.getRawContext().get("current_shop_anchor"));
        assertNotNull(resolved.getRawContext().get("current_constraints"));
        assertEquals("entity_reference", resolved.getRawContext().get("follow_up_kind"));
        assertEquals(Boolean.FALSE, resolved.getRawContext().get("needs_clarification"));
    }

    @Test
    void resolveContextShouldRecoverShopAndTargetUserFromBlogContext() {
        Map<String, Object> context = new HashMap<>();
        context.put("blogId", 11L);

        Blog blog = new Blog();
        blog.setId(11L);
        blog.setShopId(22L);
        blog.setUserId(33L);
        blog.setTitle("探店笔记");

        Shop shop = new Shop();
        shop.setId(22L);
        shop.setName("博客关联店铺");
        shop.setTypeId(44L);

        ShopType type = new ShopType();
        type.setId(44L);
        type.setName("餐厅");

        when(blogService.getById(11L)).thenReturn(blog);
        when(shopService.getById(22L)).thenReturn(shop);
        when(shopTypeService.getById(44L)).thenReturn(type);

        AiQueryContext resolved = facade.resolveContext(context, null);

        assertEquals(Long.valueOf(11L), resolved.getBlogId());
        assertEquals(Long.valueOf(22L), resolved.getShopId());
        assertEquals(Long.valueOf(33L), resolved.getTargetUserId());
        assertEquals("探店笔记", resolved.getBlogTitle());
        assertEquals(Long.valueOf(44L), resolved.getTypeId());
        assertEquals("餐厅", resolved.getTypeName());
    }

    @Test
    void resolveRouteShouldRespectCompareVoucherRecommendAndDetailPriority() {
        AiQueryContext shopContext = new AiQueryContext();
        shopContext.setShopId(1L);
        shopContext.setShopName("海底捞");

        assertEquals(AiRouteType.COMPARE, facade.resolveRoute("海底捞和巴奴哪个好", shopContext));
        assertEquals(AiRouteType.VOUCHER, facade.resolveRoute("海底捞有什么优惠券", shopContext));
        assertEquals(AiRouteType.RECOMMEND, facade.resolveRoute("推荐附近适合约会的餐厅", shopContext));
        assertEquals(AiRouteType.DETAIL, facade.resolveRoute("这家怎么样", shopContext));
        assertEquals(AiRouteType.FAQ, facade.resolveRoute("今天天气怎么样", shopContext));
    }

    @Test
    void resolveRouteShouldTreatContextualDetailAsMerchantQuestion() {
        AiQueryContext context = new AiQueryContext();
        context.setShopId(8L);
        context.setShopName("示例商家");

        assertEquals(AiRouteType.DETAIL, facade.resolveRoute("这个店口碑怎么样", context));
        assertEquals(AiRouteType.DETAIL, facade.resolveRoute("这家详情如何", context));
    }

    private Map<String, Object> linkedMap(Object... entries) {
        Map<String, Object> map = new HashMap<>();
        for (int i = 0; i + 1 < entries.length; i += 2) {
            map.put(String.valueOf(entries[i]), entries[i + 1]);
        }
        return map;
    }
}
