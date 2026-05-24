package com.hmdp.dto.ai.internal;

import lombok.Data;

import java.util.LinkedHashMap;
import java.util.Map;

@Data
public class AiInternalShopSearchRequest {
    private String message;
    private Integer limit;
    private Long userId;
    private String userNickName;
    private Map<String, Object> context = new LinkedHashMap<>();
}
