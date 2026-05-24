package com.hmdp.ai.query.dto;

import com.hmdp.ai.query.AiQueryContext;
import com.hmdp.entity.Blog;
import com.hmdp.entity.BlogComments;
import com.hmdp.entity.Shop;
import com.hmdp.entity.ShopType;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * 口碑摘要的只读输入数据。
 */
@Data
@NoArgsConstructor
public class AiReputationDigest {

    private AiQueryContext context;
    private Shop shop;
    private ShopType shopType;
    private List<Blog> blogs = new ArrayList<>();
    private List<BlogComments> comments = new ArrayList<>();
    private List<String> highlights = new ArrayList<>();
    private String summary;
}
