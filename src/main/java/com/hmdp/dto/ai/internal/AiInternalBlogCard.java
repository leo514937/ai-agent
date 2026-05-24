package com.hmdp.dto.ai.internal;

import lombok.Data;

@Data
public class AiInternalBlogCard {
    private Long id;
    private Long shopId;
    private Long userId;
    private String title;
    private String content;
    private Integer liked;
    private Integer comments;
}
