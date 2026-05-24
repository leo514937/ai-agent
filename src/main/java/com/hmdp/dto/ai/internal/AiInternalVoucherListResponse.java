package com.hmdp.dto.ai.internal;

import com.hmdp.dto.ai.AiVoucherCard;
import lombok.Data;

import java.util.ArrayList;
import java.util.List;

@Data
public class AiInternalVoucherListResponse {
    private Long shopId;
    private String shopName;
    private List<AiVoucherCard> vouchers = new ArrayList<>();
}
