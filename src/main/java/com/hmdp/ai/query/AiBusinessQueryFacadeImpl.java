package com.hmdp.ai.query;

import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.hmdp.ai.query.dto.AiCompareDigest;
import com.hmdp.ai.query.dto.AiReputationDigest;
import com.hmdp.ai.query.dto.AiShopDetailDigest;
import com.hmdp.ai.query.dto.AiUserContextDigest;
import com.hmdp.dto.Result;
import com.hmdp.dto.UserDTO;
import com.hmdp.entity.Blog;
import com.hmdp.entity.BlogComments;
import com.hmdp.entity.Shop;
import com.hmdp.entity.ShopType;
import com.hmdp.entity.User;
import com.hmdp.entity.UserInfo;
import com.hmdp.entity.Voucher;
import com.hmdp.service.IBlogCommentsService;
import com.hmdp.service.IBlogService;
import com.hmdp.service.IFollowService;
import com.hmdp.service.IShopService;
import com.hmdp.service.IShopTypeService;
import com.hmdp.service.IUserInfoService;
import com.hmdp.service.IUserService;
import com.hmdp.service.IVoucherService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import javax.annotation.Resource;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Collectors;

/**
 * 点评业务只读查询适配层默认实现。
 */
@Service
@Transactional(readOnly = true)
public class AiBusinessQueryFacadeImpl implements AiBusinessQueryFacade {

    @Resource
    private IShopService shopService;
    @Resource
    private IVoucherService voucherService;
    @Resource
    private IBlogService blogService;
    @Resource
    private IShopTypeService shopTypeService;
    @Resource
    private IUserService userService;
    @Resource
    private IUserInfoService userInfoService;
    @Resource
    private IFollowService followService;
    @Resource
    private IBlogCommentsService blogCommentsService;

    @Override
    public AiQueryContext resolveContext(Map<String, Object> context, UserDTO currentUser) {
        AiQueryContext result = AiQueryContext.from(context, currentUser);
        if (result.getShopId() == null && !result.getCurrentShopAnchor().isEmpty()) {
            Object anchorShopId = result.getCurrentShopAnchor().get("shop_id");
            if (anchorShopId == null) {
                anchorShopId = result.getCurrentShopAnchor().get("shopId");
            }
            if (anchorShopId == null) {
                anchorShopId = result.getCurrentShopAnchor().get("id");
            }
            if (anchorShopId instanceof Number) {
                result.setShopId(((Number) anchorShopId).longValue());
            }
            if (StrUtil.isBlank(result.getShopName())) {
                Object anchorName = result.getCurrentShopAnchor().get("name");
                if (anchorName == null) {
                    anchorName = result.getCurrentShopAnchor().get("shop_name");
                }
                if (anchorName == null) {
                    anchorName = result.getCurrentShopAnchor().get("shopName");
                }
                if (anchorName != null) {
                    result.setShopName(String.valueOf(anchorName));
                }
            }
        }
        if (StrUtil.isBlank(result.getTypeName()) && result.hasConstraintContext()) {
            Object category = result.getCurrentConstraints().get("category");
            if (category != null) {
                result.setTypeName(String.valueOf(category));
            }
        }
        Map<String, Object> rawContext = result.getRawContext();
        if (rawContext != null) {
            if (!result.getCurrentShopAnchor().isEmpty()) {
                rawContext.put("current_shop_anchor", new LinkedHashMap<>(result.getCurrentShopAnchor()));
            }
            if (!result.getDialogComparisonTargets().isEmpty()) {
                rawContext.put("dialog_comparison_targets", new ArrayList<>(result.getDialogComparisonTargets()));
            }
            if (!result.getCurrentConstraints().isEmpty()) {
                rawContext.put("current_constraints", new LinkedHashMap<>(result.getCurrentConstraints()));
            }
            if (result.getFollowUpKind() != null) {
                rawContext.put("follow_up_kind", result.getFollowUpKind());
            }
            rawContext.put("needs_clarification", result.requiresClarification());
        }
        Blog currentBlog = resolveBlog(result.getBlogId());
        if (currentBlog != null) {
            result.setBlogId(currentBlog.getId());
            if (result.getShopId() == null && currentBlog.getShopId() != null) {
                result.setShopId(currentBlog.getShopId());
            }
            if (result.getTargetUserId() == null && currentBlog.getUserId() != null) {
                result.setTargetUserId(currentBlog.getUserId());
            }
            if (StrUtil.isBlank(result.getBlogTitle())) {
                result.setBlogTitle(currentBlog.getTitle());
            }
        }

        Shop currentShop = resolveShop(result);
        if (currentShop != null) {
            result.setShopId(currentShop.getId());
            if (StrUtil.isBlank(result.getShopName())) {
                result.setShopName(currentShop.getName());
            }
            if (result.getTypeId() == null && currentShop.getTypeId() != null) {
                result.setTypeId(currentShop.getTypeId());
            }
        }

        ShopType currentType = resolveType(result, currentShop);
        if (currentType != null) {
            result.setTypeId(currentType.getId());
            if (StrUtil.isBlank(result.getTypeName())) {
                result.setTypeName(currentType.getName());
            }
        }

        return result;
    }

    @Override
    public AiRouteType resolveRoute(String message, AiQueryContext context) {
        String text = normalizeText(message);
        if (containsAny(text, "对比", "比较", "哪个好", "怎么选", "选哪个", "差异")) {
            return AiRouteType.COMPARE;
        }
        if (containsAny(text, "优惠券", "优惠", "券", "代金券", "秒杀", "抢购", "划算")) {
            return AiRouteType.VOUCHER;
        }
        if (containsAny(text, "推荐", "附近", "找店", "找一家", "想吃", "想去", "预算", "适合")) {
            return AiRouteType.RECOMMEND;
        }
        boolean merchantReference = containsAny(text, "这家", "这家店", "这个店", "该店", "门店", "这间", "当前这家");
        if (context != null && context.hasShopContext() && merchantReference && containsAny(text, "值不值", "口碑", "评价", "评论", "评分", "详情", "怎么样", "好不好")) {
            return AiRouteType.DETAIL;
        }
        return AiRouteType.FAQ;
    }

    @Override
    public List<Shop> recommendCandidates(AiQueryContext context, int limit) {
        if (limit <= 0) {
            return Collections.emptyList();
        }
        AiQueryContext safeContext = context == null ? new AiQueryContext() : context;
        Shop currentShop = resolveShop(safeContext);
        Long typeId = resolveTypeId(safeContext, currentShop);

        List<Shop> shops;
        if (safeContext.getX() != null && safeContext.getY() != null && typeId != null) {
            shops = extractShopList(shopService.queryShopById(typeId.intValue(), 1, safeContext.getX(), safeContext.getY()));
        } else if (typeId != null) {
            shops = shopService.query()
                    .eq("type_id", typeId)
                    .orderByDesc("score")
                    .orderByDesc("sold")
                    .orderByDesc("comments")
                    .page(new Page<>(1, limit + 3))
                    .getRecords();
        } else if (StrUtil.isNotBlank(safeContext.getTypeName())) {
            shops = shopService.query()
                    .like("name", safeContext.getTypeName())
                    .orderByDesc("score")
                    .orderByDesc("sold")
                    .orderByDesc("comments")
                    .page(new Page<>(1, limit + 3))
                    .getRecords();
        } else {
            shops = shopService.query()
                    .orderByDesc("score")
                    .orderByDesc("sold")
                    .orderByDesc("comments")
                    .page(new Page<>(1, limit + 3))
                    .getRecords();
        }

        List<Shop> result = new ArrayList<>(shops == null ? Collections.<Shop>emptyList() : shops);
        if (currentShop != null) {
            result.removeIf(shop -> Objects.equals(shop.getId(), currentShop.getId()));
        }
        if (result.size() > limit) {
            result = result.subList(0, limit);
        }
        return result;
    }

    @Override
    public List<Voucher> listVouchers(AiQueryContext context, int limit) {
        if (limit <= 0) {
            return Collections.emptyList();
        }
        AiQueryContext safeContext = context == null ? new AiQueryContext() : context;
        Shop currentShop = resolveShop(safeContext);
        if (currentShop != null) {
            return loadVouchersByShop(currentShop.getId(), limit);
        }
        Long typeId = resolveTypeId(safeContext, null);
        if (typeId == null) {
            return Collections.emptyList();
        }
        List<Shop> candidates = recommendCandidates(safeContext, limit);
        List<Voucher> vouchers = new ArrayList<>();
        for (Shop shop : candidates) {
            vouchers.addAll(loadVouchersByShop(shop.getId(), 1));
            if (vouchers.size() >= limit) {
                break;
            }
        }
        if (vouchers.size() > limit) {
            return new ArrayList<>(vouchers.subList(0, limit));
        }
        return vouchers;
    }

    @Override
    public AiShopDetailDigest buildShopDetailDigest(AiQueryContext context, int voucherLimit, int blogLimit) {
        AiQueryContext safeContext = context == null ? new AiQueryContext() : context;
        Shop shop = resolveShop(safeContext);
        if (shop == null) {
            AiShopDetailDigest digest = new AiShopDetailDigest();
            digest.setContext(safeContext);
            digest.setKnownConstraints(new LinkedHashMap<>(safeContext.getCurrentConstraints()));
            digest.setComparisonTargets(new ArrayList<>(safeContext.getDialogComparisonTargets()));
            digest.setFollowUpKind(safeContext.getFollowUpKind());
            digest.setHighlights(Collections.singletonList("当前没有定位到具体店铺，可先补充店名或从店铺页进入。"));
            digest.setSummary("未找到店铺详情数据。");
            return digest;
        }

        ShopType type = resolveType(safeContext, shop);
        List<Voucher> vouchers = loadVouchersByShop(shop.getId(), voucherLimit);
        List<Blog> blogs = loadBlogsByShop(shop.getId(), blogLimit);
        AiUserContextDigest userContext = buildUserContextInternal(safeContext, safeContext.getTargetUserId());

        AiShopDetailDigest digest = new AiShopDetailDigest();
        digest.setContext(safeContext);
        digest.setShop(shop);
        digest.setShopType(type);
        digest.setVouchers(vouchers);
        digest.setBlogs(blogs);
        digest.setUserContext(userContext);
        digest.setKnownConstraints(new LinkedHashMap<>(safeContext.getCurrentConstraints()));
        digest.setComparisonTargets(new ArrayList<>(safeContext.getDialogComparisonTargets()));
        digest.setFollowUpKind(safeContext.getFollowUpKind());
        digest.setHighlights(buildShopHighlights(shop, type, vouchers, blogs, userContext));
        digest.setSummary(buildShopSummary(shop, type, vouchers, blogs, userContext));
        return digest;
    }

    @Override
    public AiCompareDigest buildCompareDigest(AiQueryContext context, int limit) {
        AiQueryContext safeContext = context == null ? new AiQueryContext() : context;
        Shop baseShop = resolveShop(safeContext);
        Long typeId = resolveTypeId(safeContext, baseShop);
        ShopType type = resolveType(safeContext, baseShop);
        List<Shop> candidates = new ArrayList<>();
        if (baseShop != null) {
            candidates.add(baseShop);
        }
        candidates.addAll(recommendCandidates(safeContext, limit + 2));
        candidates = dedupeShops(candidates);
        if (candidates.size() > limit) {
            candidates = candidates.subList(0, limit);
        }

        AiCompareDigest digest = new AiCompareDigest();
        digest.setContext(safeContext);
        digest.setBaseShop(baseShop);
        digest.setShopType(type);
        digest.setCandidates(candidates);
        digest.setCompareAxes(defaultCompareAxes());
        digest.setComparisonTargets(new ArrayList<>(safeContext.getDialogComparisonTargets()));
        digest.setKnownConstraints(new LinkedHashMap<>(safeContext.getCurrentConstraints()));
        digest.setFollowUpKind(safeContext.getFollowUpKind());
        digest.setHighlights(buildCompareHighlights(candidates, baseShop, typeId));
        digest.setSummary(buildCompareSummary(candidates, baseShop, type));
        return digest;
    }

    @Override
    public AiReputationDigest buildReputationDigest(AiQueryContext context, int blogLimit, int commentLimit) {
        AiQueryContext safeContext = context == null ? new AiQueryContext() : context;
        Shop shop = resolveShop(safeContext);
        if (shop == null) {
            AiReputationDigest digest = new AiReputationDigest();
            digest.setContext(safeContext);
            digest.setHighlights(Collections.singletonList("当前没有足够的店铺信息，先补充店名或店铺页上下文。"));
            digest.setSummary("未找到口碑摘要数据。");
            return digest;
        }

        ShopType type = resolveType(safeContext, shop);
        List<Blog> blogs = loadBlogsByShop(shop.getId(), blogLimit);
        List<BlogComments> comments = loadCommentsByBlogs(blogs, commentLimit);

        AiReputationDigest digest = new AiReputationDigest();
        digest.setContext(safeContext);
        digest.setShop(shop);
        digest.setShopType(type);
        digest.setBlogs(blogs);
        digest.setComments(comments);
        digest.setHighlights(buildReputationHighlights(shop, blogs, comments));
        digest.setSummary(buildReputationSummary(shop, type, blogs, comments));
        return digest;
    }

    @Override
    public AiUserContextDigest buildUserContextDigest(AiQueryContext context) {
        AiQueryContext safeContext = context == null ? new AiQueryContext() : context;
        return buildUserContextInternal(safeContext, safeContext.getTargetUserId());
    }

    private AiUserContextDigest buildUserContextInternal(AiQueryContext context, Long targetUserId) {
        AiUserContextDigest digest = new AiUserContextDigest();
        if (context.getUserId() != null) {
            User user = userService.getById(context.getUserId());
            digest.setUser(user);
            if (user != null) {
                UserInfo userInfo = userInfoService.getById(user.getId());
                digest.setUserInfo(userInfo);
            }
        }
        digest.setTargetUserId(targetUserId);
        if (targetUserId != null) {
            User targetUser = userService.getById(targetUserId);
            digest.setTargetUser(targetUser);
            if (targetUser != null) {
                digest.setTargetUserInfo(userInfoService.getById(targetUser.getId()));
            }
            if (context.getUserId() != null) {
                digest.setFollowingTarget(isFollowing(context.getUserId(), targetUserId));
                digest.setTargetFollowingCurrent(isFollowing(targetUserId, context.getUserId()));
            }
        }
        digest.setHighlights(buildUserHighlights(digest));
        return digest;
    }

    private Shop resolveShop(AiQueryContext context) {
        if (context == null) {
            return null;
        }
        if (context.getShopId() != null) {
            Shop shop = shopService.getById(context.getShopId());
            if (shop != null) {
                return shop;
            }
        }
        if (context.getBlogId() != null) {
            Blog blog = resolveBlog(context.getBlogId());
            if (blog != null && blog.getShopId() != null) {
                Shop shop = shopService.getById(blog.getShopId());
                if (shop != null) {
                    return shop;
                }
            }
        }
        if (StrUtil.isNotBlank(context.getShopName())) {
            List<Shop> shops = shopService.query()
                    .like("name", context.getShopName())
                    .orderByDesc("score")
                    .page(new Page<>(1, 1))
                    .getRecords();
            if (!shops.isEmpty()) {
                return shops.get(0);
            }
        }
        return null;
    }

    private Blog resolveBlog(Long blogId) {
        if (blogId == null) {
            return null;
        }
        return blogService.getById(blogId);
    }

    private ShopType resolveType(AiQueryContext context, Shop currentShop) {
        if (context != null && context.getTypeId() != null) {
            ShopType type = shopTypeService.getById(context.getTypeId());
            if (type != null) {
                return type;
            }
        }
        if (currentShop != null && currentShop.getTypeId() != null) {
            ShopType type = shopTypeService.getById(currentShop.getTypeId());
            if (type != null) {
                return type;
            }
        }
        if (context != null && StrUtil.isNotBlank(context.getTypeName())) {
            for (ShopType type : shopTypeService.list()) {
                if (containsIgnoreCase(type.getName(), context.getTypeName())) {
                    return type;
                }
            }
        }
        return null;
    }

    private Long resolveTypeId(AiQueryContext context, Shop currentShop) {
        if (context != null && context.getTypeId() != null) {
            return context.getTypeId();
        }
        if (currentShop != null) {
            return currentShop.getTypeId();
        }
        if (context != null && StrUtil.isNotBlank(context.getTypeName())) {
            for (ShopType type : shopTypeService.list()) {
                if (containsIgnoreCase(type.getName(), context.getTypeName())) {
                    return type.getId();
                }
            }
        }
        return null;
    }

    private List<Shop> dedupeShops(List<Shop> shops) {
        Map<Long, Shop> map = new LinkedHashMap<>();
        for (Shop shop : shops) {
            if (shop != null && shop.getId() != null && !map.containsKey(shop.getId())) {
                map.put(shop.getId(), shop);
            }
        }
        return new ArrayList<>(map.values());
    }

    private List<Voucher> loadVouchersByShop(Long shopId, int limit) {
        if (shopId == null || limit <= 0) {
            return Collections.emptyList();
        }
        return voucherService.query()
                .eq("shop_id", shopId)
                .orderByDesc("status")
                .orderByDesc("create_time")
                .page(new Page<>(1, limit))
                .getRecords();
    }

    private List<Blog> loadBlogsByShop(Long shopId, int limit) {
        if (shopId == null || limit <= 0) {
            return Collections.emptyList();
        }
        return blogService.query()
                .eq("shop_id", shopId)
                .orderByDesc("liked")
                .orderByDesc("comments")
                .page(new Page<>(1, limit))
                .getRecords();
    }

    private List<BlogComments> loadCommentsByBlogs(List<Blog> blogs, int limit) {
        if (blogs == null || blogs.isEmpty() || limit <= 0) {
            return Collections.emptyList();
        }
        List<Long> blogIds = blogs.stream()
                .map(Blog::getId)
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
        if (blogIds.isEmpty()) {
            return Collections.emptyList();
        }
        return blogCommentsService.query()
                .in("blog_id", blogIds)
                .orderByDesc("liked")
                .orderByDesc("create_time")
                .page(new Page<>(1, limit))
                .getRecords();
    }

    private boolean isFollowing(Long userId, Long targetUserId) {
        if (userId == null || targetUserId == null) {
            return false;
        }
        return followService.query()
                .eq("user_id", userId)
                .eq("follow_user_id", targetUserId)
                .count() > 0;
    }

    private List<Shop> extractShopList(Result result) {
        if (result == null || result.getData() == null) {
            return Collections.emptyList();
        }
        Object data = result.getData();
        if (data instanceof List) {
            List<?> list = (List<?>) data;
            List<Shop> shops = new ArrayList<>();
            for (Object item : list) {
                if (item instanceof Shop) {
                    shops.add((Shop) item);
                }
            }
            return shops;
        }
        return Collections.emptyList();
    }

    private String buildShopSummary(Shop shop, ShopType type, List<Voucher> vouchers, List<Blog> blogs, AiUserContextDigest userContext) {
        List<String> lines = new ArrayList<>();
        lines.add(shop.getName() + " 位于 " + defaultString(shop.getArea(), "未知商圈") + "，人均约 " + formatPrice(shop.getAvgPrice()) + " 元，评分 " + formatScore(shop.getScore()) + "，评论 " + defaultNumber(shop.getComments()) + " 条。");
        if (type != null && StrUtil.isNotBlank(type.getName())) {
            lines.add("店铺类型：" + type.getName() + "。");
        }
        if (StrUtil.isNotBlank(shop.getOpenHours())) {
            lines.add("营业时间：" + shop.getOpenHours() + "。");
        }
        if (!vouchers.isEmpty()) {
            Voucher voucher = vouchers.get(0);
            lines.add("可优先参考的优惠券是「" + voucher.getTitle() + "」，到手价 " + formatPrice(voucher.getPayValue()) + " 元，抵扣 " + formatPrice(voucher.getActualValue()) + " 元。");
        }
        if (!blogs.isEmpty()) {
            String blogTitles = blogs.stream()
                    .limit(3)
                    .map(Blog::getTitle)
                    .filter(StrUtil::isNotBlank)
                    .collect(Collectors.joining("、"));
            if (StrUtil.isNotBlank(blogTitles)) {
                lines.add("可先看这些探店笔记：" + blogTitles + "。");
            }
        }
        if (userContext != null && userContext.isFollowingTarget()) {
            lines.add("当前用户已关注相关作者，适合优先看他们的内容。");
        }
        return String.join("\n", lines);
    }

    private List<String> buildShopHighlights(Shop shop, ShopType type, List<Voucher> vouchers, List<Blog> blogs, AiUserContextDigest userContext) {
        List<String> highlights = new ArrayList<>();
        if (type != null && StrUtil.isNotBlank(type.getName())) {
            highlights.add("类型：" + type.getName());
        }
        if (shop.getScore() != null) {
            highlights.add("评分：" + formatScore(shop.getScore()));
        }
        if (shop.getAvgPrice() != null) {
            highlights.add("人均：" + formatPrice(shop.getAvgPrice()) + " 元");
        }
        if (shop.getComments() != null) {
            highlights.add("评论量：" + shop.getComments());
        }
        if (!vouchers.isEmpty()) {
            highlights.add("优惠券：" + vouchers.size() + " 张");
        }
        if (!blogs.isEmpty()) {
            highlights.add("相关笔记：" + blogs.size() + " 篇");
        }
        if (userContext != null && userContext.isFollowingTarget()) {
            highlights.add("已关注作者");
        }
        return highlights;
    }

    private String buildCompareSummary(List<Shop> candidates, Shop baseShop, ShopType type) {
        if (candidates == null || candidates.isEmpty()) {
            return "暂时没有拿到可比较的商家数据。";
        }
        List<String> lines = new ArrayList<>();
        lines.add("我先把 " + candidates.size() + " 家可比较商家整理出来了。");
        if (type != null && StrUtil.isNotBlank(type.getName())) {
            lines.add("对比范围优先按 " + type.getName() + " 来看。");
        }
        for (int i = 0; i < Math.min(candidates.size(), 3); i++) {
            Shop shop = candidates.get(i);
            lines.add((i + 1) + ". " + shop.getName() + "，评分 " + formatScore(shop.getScore()) + "，人均约 " + formatPrice(shop.getAvgPrice()) + " 元，评论 " + defaultNumber(shop.getComments()) + " 条。");
        }
        if (baseShop != null) {
            lines.add("如果你想围绕当前店对比，我也可以再按价格、评分、评价量继续细化。");
        }
        return String.join("\n", lines);
    }

    private List<String> buildCompareHighlights(List<Shop> candidates, Shop baseShop, Long typeId) {
        List<String> highlights = new ArrayList<>();
        if (baseShop != null) {
            highlights.add("基准店：" + baseShop.getName());
        }
        if (typeId != null) {
            highlights.add("同类型优先");
        }
        if (candidates != null && !candidates.isEmpty()) {
            highlights.add("候选店：" + candidates.size() + " 家");
        }
        highlights.add("比较维度：评分 / 人均 / 评论量 / 营业时间");
        return highlights;
    }

    private List<String> defaultCompareAxes() {
        List<String> axes = new ArrayList<>();
        axes.add("评分");
        axes.add("人均");
        axes.add("评论量");
        axes.add("营业时间");
        return axes;
    }

    private String buildReputationSummary(Shop shop, ShopType type, List<Blog> blogs, List<BlogComments> comments) {
        List<String> lines = new ArrayList<>();
        lines.add("「" + shop.getName() + "」的口碑摘要：");
        if (type != null && StrUtil.isNotBlank(type.getName())) {
            lines.add("类型：" + type.getName() + "。");
        }
        if (!blogs.isEmpty()) {
            String titles = blogs.stream()
                    .limit(3)
                    .map(Blog::getTitle)
                    .filter(StrUtil::isNotBlank)
                    .collect(Collectors.joining("、"));
            if (StrUtil.isNotBlank(titles)) {
                lines.add("相关探店笔记：" + titles + "。");
            }
        }
        if (!comments.isEmpty()) {
            lines.add("已抓取到 " + comments.size() + " 条评论/回复作为口碑输入。");
        } else if (shop.getComments() != null) {
            lines.add("店铺评论量约 " + shop.getComments() + " 条，可优先从高赞笔记里归纳口碑。");
        }
        lines.add("后续可继续追问：优点、差评点、值不值、和同类店怎么选。");
        return String.join("\n", lines);
    }

    private List<String> buildReputationHighlights(Shop shop, List<Blog> blogs, List<BlogComments> comments) {
        List<String> highlights = new ArrayList<>();
        if (shop.getScore() != null) {
            highlights.add("评分：" + formatScore(shop.getScore()));
        }
        if (shop.getComments() != null) {
            highlights.add("评论量：" + shop.getComments());
        }
        if (!blogs.isEmpty()) {
            highlights.add("笔记：" + blogs.size() + " 篇");
        }
        if (!comments.isEmpty()) {
            highlights.add("评论/回复：" + comments.size() + " 条");
        }
        return highlights;
    }

    private List<String> buildUserHighlights(AiUserContextDigest digest) {
        List<String> highlights = new ArrayList<>();
        if (digest.getUser() != null && StrUtil.isNotBlank(digest.getUser().getNickName())) {
            highlights.add("当前用户：" + digest.getUser().getNickName());
        }
        if (digest.getUserInfo() != null && StrUtil.isNotBlank(digest.getUserInfo().getCity())) {
            highlights.add("城市：" + digest.getUserInfo().getCity());
        }
        if (digest.getTargetUser() != null && StrUtil.isNotBlank(digest.getTargetUser().getNickName())) {
            highlights.add("目标用户：" + digest.getTargetUser().getNickName());
        }
        if (digest.isFollowingTarget()) {
            highlights.add("已关注目标");
        }
        return highlights;
    }

    private String normalizeText(String message) {
        return message == null ? "" : message.trim();
    }

    private boolean containsAny(String source, String... keywords) {
        if (StrUtil.isBlank(source)) {
            return false;
        }
        for (String keyword : keywords) {
            if (StrUtil.isNotBlank(keyword) && source.contains(keyword)) {
                return true;
            }
        }
        return false;
    }

    private boolean containsIgnoreCase(String source, String keyword) {
        if (StrUtil.isBlank(source) || StrUtil.isBlank(keyword)) {
            return false;
        }
        return source.toLowerCase().contains(keyword.toLowerCase());
    }

    private String defaultString(String value, String defaultValue) {
        return StrUtil.isNotBlank(value) ? value : defaultValue;
    }

    private String defaultNumber(Integer value) {
        return value == null ? "0" : String.valueOf(value);
    }

    private String formatScore(Integer score) {
        if (score == null) {
            return "0.0";
        }
        return String.format(java.util.Locale.CHINA, "%.1f", score / 10.0);
    }

    private String formatPrice(Long price) {
        if (price == null) {
            return "未知";
        }
        return String.valueOf(price);
    }
}
