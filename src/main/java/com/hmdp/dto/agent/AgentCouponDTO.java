package com.hmdp.dto.agent;

import com.fasterxml.jackson.databind.PropertyNamingStrategy;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Coupon DTO for the Agent tool API.
 *
 * Field mapping from tb_voucher:
 *   id           → couponId
 *   shop_id      → shopId
 *   title        → title
 *   sub_title    → description
 *   pay_value    → payValue  (unit: fen/cents)
 *   actual_value → actualValue (unit: fen/cents)
 *   status       → status  (1=available)
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
@JsonNaming(PropertyNamingStrategy.SnakeCaseStrategy.class)
public class AgentCouponDTO {
    private String couponId;
    private String shopId;
    private String title;
    private String description;    // from sub_title
    private String discountType;
    private Double discountValue;
    private Double minConsume;
    private String validFrom;
    private String validUntil;
    private Integer stock;
    private Long payValue;         // unit: fen
    private Long actualValue;      // unit: fen
    private String status;         // "available" | "expired" | "unknown"
}
