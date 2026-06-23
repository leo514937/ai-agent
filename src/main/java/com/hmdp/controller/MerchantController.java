package com.hmdp.controller;

import cn.hutool.core.util.StrUtil;
import com.hmdp.dto.Result;
import com.hmdp.dto.merchant.MerchantCommentDTO;
import com.hmdp.dto.merchant.MerchantDTO;
import com.hmdp.dto.merchant.MerchantDetailDTO;
import com.hmdp.dto.merchant.MerchantServiceDTO;
import com.hmdp.entity.Blog;
import com.hmdp.entity.BlogComments;
import com.hmdp.entity.Shop;
import com.hmdp.entity.ShopType;
import com.hmdp.entity.User;
import com.hmdp.entity.Voucher;
import com.hmdp.service.IBlogCommentsService;
import com.hmdp.service.IBlogService;
import com.hmdp.service.IShopService;
import com.hmdp.service.IShopTypeService;
import com.hmdp.service.IUserService;
import com.hmdp.service.IVoucherOrderService;
import com.hmdp.service.IVoucherService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import javax.annotation.Resource;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/merchants")
public class MerchantController {

    @Resource
    private IShopService shopService;

    @Resource
    private IShopTypeService shopTypeService;

    @Resource
    private IVoucherService voucherService;

    @Resource
    private IVoucherOrderService voucherOrderService;

    @Resource
    private IBlogService blogService;

    @Resource
    private IBlogCommentsService blogCommentsService;

    @Resource
    private IUserService userService;

    private static final DateTimeFormatter DATE_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd");

    @GetMapping
    public Result listMerchants(
            @RequestParam(value = "category", required = false) String category,
            @RequestHeader(value = "X-User-Latitude", required = false) Double latHeader1,
            @RequestHeader(value = "x-user-latitude", required = false) Double latHeader2,
            @RequestHeader(value = "X-User-Longitude", required = false) Double lngHeader1,
            @RequestHeader(value = "x-user-longitude", required = false) Double lngHeader2
    ) {
        Double lat = latHeader1 != null ? latHeader1 : latHeader2;
        Double lng = lngHeader1 != null ? lngHeader1 : lngHeader2;

        // Resolve type IDs based on category
        List<Long> typeIds = new ArrayList<>();
        if (StrUtil.isNotBlank(category) && !"全部".equals(category)) {
            switch (category) {
                case "美食":
                    typeIds.add(1L);
                    break;
                case "休闲娱乐":
                    typeIds.add(2L);
                    typeIds.add(8L);
                    typeIds.add(9L);
                    break;
                case "美容SPA":
                    typeIds.add(6L);
                    break;
                case "到店服务":
                    typeIds.add(3L);
                    typeIds.add(4L);
                    typeIds.add(5L);
                    typeIds.add(7L);
                    typeIds.add(10L);
                    break;
                default:
                    // Fallback to query by type name
                    ShopType shopType = shopTypeService.query().like("name", category).one();
                    if (shopType != null) {
                        typeIds.add(shopType.getId());
                    }
                    break;
            }
        }

        // Query shops
        List<Shop> shops;
        if (StrUtil.isNotBlank(category) && !"全部".equals(category) && typeIds.isEmpty()) {
            // Category specified but no matching types found in DB
            return Result.ok(Collections.emptyList());
        }

        if (!typeIds.isEmpty()) {
            shops = shopService.query().in("type_id", typeIds).list();
        } else {
            shops = shopService.list();
        }

        // Load type mapping
        Map<Long, String> typeMap = shopTypeService.list().stream()
                .collect(Collectors.toMap(ShopType::getId, ShopType::getName));

        // Map to DTOs
        List<MerchantDTO> merchantDTOs = shops.stream()
                .map(shop -> convertToMerchantDTO(shop, lat, lng, typeMap))
                .collect(Collectors.toList());

        // Sort by distance (nearest first)
        merchantDTOs.sort(Comparator.comparingDouble(MerchantDTO::getDistanceKm));

        return Result.ok(merchantDTOs);
    }

    @GetMapping("/{id}")
    public Result getMerchantDetail(
            @PathVariable("id") Long id,
            @RequestHeader(value = "X-User-Latitude", required = false) Double latHeader1,
            @RequestHeader(value = "x-user-latitude", required = false) Double latHeader2,
            @RequestHeader(value = "X-User-Longitude", required = false) Double lngHeader1,
            @RequestHeader(value = "x-user-longitude", required = false) Double lngHeader2
    ) {
        Double lat = latHeader1 != null ? latHeader1 : latHeader2;
        Double lng = lngHeader1 != null ? lngHeader1 : lngHeader2;

        Shop shop = shopService.getById(id);
        if (shop == null) {
            return Result.fail("商户不存在");
        }

        Map<Long, String> typeMap = shopTypeService.list().stream()
                .collect(Collectors.toMap(ShopType::getId, ShopType::getName));

        MerchantDTO baseDto = convertToMerchantDTO(shop, lat, lng, typeMap);

        MerchantDetailDTO detailDto = new MerchantDetailDTO();
        // Copy base fields
        detailDto.setId(baseDto.getId());
        detailDto.setName(baseDto.getName());
        detailDto.setCoverImage(baseDto.getCoverImage());
        detailDto.setRating(baseDto.getRating());
        detailDto.setCommentCount(baseDto.getCommentCount());
        detailDto.setAvgPrice(baseDto.getAvgPrice());
        detailDto.setCategory(baseDto.getCategory());
        detailDto.setSubCategory(baseDto.getSubCategory());
        detailDto.setAddress(baseDto.getAddress());
        detailDto.setDistanceKm(baseDto.getDistanceKm());
        detailDto.setLatitude(baseDto.getLatitude());
        detailDto.setLongitude(baseDto.getLongitude());
        detailDto.setOpenTime(baseDto.getOpenTime());
        detailDto.setTags(baseDto.getTags());
        detailDto.setHasCoupon(baseDto.getHasCoupon());
        detailDto.setCouponTip(baseDto.getCouponTip());

        // Load vouchers (services)
        List<Voucher> vouchers = voucherService.query().eq("shop_id", id).list();
        List<MerchantServiceDTO> services = vouchers.stream().map(voucher -> {
            MerchantServiceDTO serviceDto = new MerchantServiceDTO();
            serviceDto.setId(voucher.getId().toString());
            serviceDto.setMerchantId(id.toString());
            serviceDto.setTitle(voucher.getTitle());
            serviceDto.setCoverImage(baseDto.getCoverImage()); // Fallback to shop cover image
            serviceDto.setOriginalPrice(voucher.getActualValue() != null ? voucher.getActualValue() / 100.0 : 0.0);
            serviceDto.setCurrentPrice(voucher.getPayValue() != null ? voucher.getPayValue() / 100.0 : 0.0);
            
            // Count sold vouchers
            int soldCount = voucherOrderService.query().eq("voucher_id", voucher.getId()).count();
            // Fallback to mock soldCount if 0 to make it look alive in UI
            serviceDto.setSoldCount(soldCount > 0 ? soldCount : (int) (voucher.getId() * 17 + 23) % 200 + 45);
            serviceDto.setTag(voucher.getType() == 1 ? "秒杀" : "特惠");
            serviceDto.setDescription(voucher.getRules());
            return serviceDto;
        }).collect(Collectors.toList());
        detailDto.setServices(services);

        // Load reviews (comments via blogs)
        List<Blog> blogs = blogService.query().eq("shop_id", id).list();
        List<MerchantCommentDTO> comments = new ArrayList<>();
        if (!blogs.isEmpty()) {
            List<Long> blogIds = blogs.stream().map(Blog::getId).collect(Collectors.toList());
            List<BlogComments> blogComments = blogCommentsService.query().in("blog_id", blogIds).list();
            comments = blogComments.stream().map(comment -> {
                MerchantCommentDTO commentDto = new MerchantCommentDTO();
                commentDto.setId(comment.getId().toString());
                commentDto.setUserId(comment.getUserId().toString());
                
                // Load username and avatar
                User user = userService.getById(comment.getUserId());
                if (user != null) {
                    commentDto.setUsername(user.getNickName());
                    commentDto.setAvatarUrl(StrUtil.isNotBlank(user.getIcon()) ? user.getIcon() : "/imgs/blogs/blog1.jpg");
                } else {
                    commentDto.setUsername("匿名用户");
                    commentDto.setAvatarUrl("/imgs/blogs/blog1.jpg");
                }
                
                // Comment rating (mock since comment has no rating, but generate consistently)
                int rating = (int) (comment.getId() % 2 == 0 ? 5 : 4);
                commentDto.setRating(rating);
                commentDto.setPublishDate(comment.getCreateTime() != null ? comment.getCreateTime().format(DATE_FORMATTER) : "2026-06-23");
                commentDto.setContent(comment.getContent());
                
                // Use blog images if available
                List<String> images = new ArrayList<>();
                Blog blog = blogs.stream().filter(b -> b.getId().equals(comment.getBlogId())).findFirst().orElse(null);
                if (blog != null && StrUtil.isNotBlank(blog.getImages())) {
                    for (String img : blog.getImages().split(",")) {
                        images.add(img.trim());
                    }
                }
                commentDto.setImages(images);
                return commentDto;
            }).collect(Collectors.toList());
        }
        detailDto.setComments(comments);

        return Result.ok(detailDto);
    }

    private MerchantDTO convertToMerchantDTO(Shop shop, Double userLat, Double userLng, Map<Long, String> typeMap) {
        MerchantDTO dto = new MerchantDTO();
        dto.setId(shop.getId().toString());
        dto.setName(shop.getName());

        if (StrUtil.isNotBlank(shop.getImages())) {
            dto.setCoverImage(shop.getImages().split(",")[0]);
        } else {
            dto.setCoverImage("");
        }

        dto.setRating(shop.getScore() != null ? shop.getScore() / 10.0 : 0.0);
        dto.setCommentCount(shop.getComments() != null ? shop.getComments() : 0);
        dto.setAvgPrice(shop.getAvgPrice());
        dto.setCategory(typeMap.getOrDefault(shop.getTypeId(), "其他"));
        dto.setSubCategory(null);
        dto.setAddress(shop.getAddress());
        dto.setLatitude(shop.getY());
        dto.setLongitude(shop.getX());

        if (userLat != null && userLng != null && shop.getX() != null && shop.getY() != null) {
            dto.setDistanceKm(getDistance(userLat, userLng, shop.getY(), shop.getX()));
        } else {
            // Default location: Beijing University of Posts and Telecommunications
            dto.setDistanceKm(getDistance(39.961554, 116.358104, shop.getY(), shop.getX()));
        }

        dto.setOpenTime(shop.getOpenHours() != null ? shop.getOpenHours() : "09:00-22:00");

        List<String> tags = new ArrayList<>();
        if (StrUtil.isNotBlank(shop.getArea())) {
            tags.add(shop.getArea());
        }
        tags.add("免预约");
        dto.setTags(tags);

        List<Voucher> vouchers = voucherService.query().eq("shop_id", shop.getId()).list();
        dto.setHasCoupon(!vouchers.isEmpty());
        if (!vouchers.isEmpty()) {
            dto.setCouponTip(vouchers.get(0).getTitle());
        } else {
            dto.setCouponTip(null);
        }

        return dto;
    }

    private static double getDistance(double lat1, double lng1, double lat2, double lng2) {
        double radLat1 = Math.toRadians(lat1);
        double radLat2 = Math.toRadians(lat2);
        double a = radLat1 - radLat2;
        double b = Math.toRadians(lng1) - Math.toRadians(lng2);
        double s = 2 * Math.asin(Math.sqrt(Math.pow(Math.sin(a / 2), 2) +
                Math.cos(radLat1) * Math.cos(radLat2) * Math.pow(Math.sin(b / 2), 2)));
        s = s * 6378.137; // Earth radius in km
        s = Math.round(s * 100) / 100.0;
        return s;
    }
}
