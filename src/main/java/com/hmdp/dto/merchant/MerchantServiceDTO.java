package com.hmdp.dto.merchant;

import lombok.Data;

@Data
public class MerchantServiceDTO {
    private String id;
    private String merchantId;
    private String title;
    private String coverImage;
    private Double originalPrice; // 原价 (Yuan)
    private Double currentPrice;  // 现价/团购价 (Yuan)
    private Integer soldCount;
    private String tag;           // 例如 "精选", "随时退"
    private String description;
}
