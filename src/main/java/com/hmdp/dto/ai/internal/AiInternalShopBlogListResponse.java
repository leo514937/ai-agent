package com.hmdp.dto.ai.internal;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

@Data
public class AiInternalShopBlogListResponse {
    private Long shopId;
    private String shopName;
    private List<AiInternalBlogCard> blogs = new ArrayList<>();
}
