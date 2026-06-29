package com.hmdp.dto.agent;

import com.fasterxml.jackson.databind.PropertyNamingStrategy;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * Lightweight shop card facts for recommendation and comparison.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
@JsonNaming(PropertyNamingStrategy.SnakeCaseStrategy.class)
public class AgentShopCardDTO {
    private String shopId;
    private String name;
    private List<String> alias = new ArrayList<>();
    private String category;
    private String address;
    private Double rating;
    private Double avgPrice;
    private String priceLevel;
    private Integer distanceM;
    private Integer etaMinutes;
    private Boolean isOpen;
    private String openStatusText;
    private Integer couponCount;
    private Boolean hasCoupon;
    private String topCouponTitle;
    private List<String> topTags = new ArrayList<>();
    private List<String> sceneTags = new ArrayList<>();
    private List<String> sourceFields = new ArrayList<>();
}
