package com.hmdp.dto.ai;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class AiVoucherCard {
    private Long id;
    private Long shopId;
    private String shopName;
    private String title;
    private String subTitle;
    private Long payValue;
    private Long actualValue;
    private Integer stock;
    private String beginTime;
    private String endTime;
    private String rules;
}
