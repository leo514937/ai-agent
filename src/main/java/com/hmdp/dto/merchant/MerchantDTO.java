package com.hmdp.dto.merchant;

import lombok.Data;
import java.util.List;

@Data
public class MerchantDTO {
    private String id;
    private String name;
    private String coverImage;
    private Double rating;         // 评分 (0.0-5.0)
    private Integer commentCount;
    private Long avgPrice;
    private String category;       // 一级分类 (如: 美食)
    private String subCategory;
    private String address;
    private Double distanceKm;     // 距离千米
    private Double latitude;
    private Double longitude;
    private String openTime;       // 营业时间 (如 "10:00-22:00")
    private List<String> tags;
    private Boolean hasCoupon;
    private String couponTip;
}
