package com.hmdp.dto.agent;

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
public class AgentCouponDTO {
    private String couponId;
    private String shopId;
    private String title;
    private String description;    // from sub_title
    private Long payValue;         // unit: fen
    private Long actualValue;      // unit: fen
    private String status;         // "available" | "expired" | "unknown"
}
