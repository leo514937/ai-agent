package com.hmdp.dto.ai.internal;

import com.hmdp.dto.ai.AiShopCard;
import com.hmdp.dto.ai.AiVoucherCard;
import lombok.Data;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Data
public class AiInternalShopDetailResponse {
    private boolean found;
    private AiShopCard shop;
    private List<AiVoucherCard> vouchers = new ArrayList<>();
    private List<String> highlights = new ArrayList<>();
    private String summary;
    private Map<String, Object> resolvedContext = new LinkedHashMap<>();
}
