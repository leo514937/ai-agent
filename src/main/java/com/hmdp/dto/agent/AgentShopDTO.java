package com.hmdp.dto.agent;

import com.fasterxml.jackson.databind.PropertyNamingStrategy;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * Shop DTO for the Agent tool API.
 *
 * Field mapping from tb_shop:
 *   id       → shop_id
 *   name     → shop_name
 *   type_id  → categoryId
 *   x        → lng  (x is longitude in DB)
 *   y        → lat  (y is latitude in DB)
 *   score    → rating  (score/10.0)
 *   avg_price → avgPrice
 *   open_hours → businessHours
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
@JsonNaming(PropertyNamingStrategy.SnakeCaseStrategy.class)
public class AgentShopDTO {
    private String shopId;
    private String shopName;
    private Long categoryId;
    private String category;       // resolved from type_id if available
    private String address;
    private List<String> alias = new ArrayList<>();
    private Double lat;            // from tb_shop.y
    private Double lng;            // from tb_shop.x
    private Double rating;         // from tb_shop.score / 10.0
    private Long avgPrice;
    private String businessHours;  // from tb_shop.open_hours
    private Integer sold;
    private Integer comments;
    private String area;
    private List<String> tags = new ArrayList<>();
}
