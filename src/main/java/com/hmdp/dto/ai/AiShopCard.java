package com.hmdp.dto.ai;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class AiShopCard {
    private Long id;
    private String name;
    private String area;
    private String address;
    private Long avgPrice;
    private Double score;
    private Integer comments;
    private String openHours;
    private String image;
    private Double distance;
    private String reason;
}
