package com.hmdp.dto.agent;

import com.fasterxml.jackson.databind.PropertyNamingStrategy;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * Request for get_shop_cards.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
@JsonNaming(PropertyNamingStrategy.SnakeCaseStrategy.class)
public class AgentShopCardsRequest {
    private List<String> shopIds = new ArrayList<>();
    private AgentLocation userLocation;
    private Boolean needCouponBrief = Boolean.TRUE;
    private Boolean needOpenStatus = Boolean.TRUE;
    private Boolean needDistanceEta = Boolean.TRUE;
    private Integer maxItems;
}
