package com.hmdp.dto.ai.internal;

import com.hmdp.dto.ai.AiShopCard;
import lombok.Data;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Data
public class AiInternalShopSearchResponse {
    private String route;
    private List<AiShopCard> shops = new ArrayList<>();
    private Map<String, Object> resolvedContext = new LinkedHashMap<>();
}
