package com.hmdp.dto.merchant;

import lombok.Data;
import java.util.List;

@Data
public class MerchantCommentDTO {
    private String id;
    private String userId;
    private String username;
    private String avatarUrl;
    private Integer rating;       // 评分 (1-5)
    private String publishDate;   // 格式如 "2026-06-23"
    private String content;
    private List<String> images;
}
