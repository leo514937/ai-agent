package com.hmdp.ai.query.dto;

import com.hmdp.ai.query.AiQueryContext;
import com.hmdp.entity.Shop;
import com.hmdp.entity.ShopType;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * 对比场景的只读输入数据。
 */
@Data
@NoArgsConstructor
public class AiCompareDigest {

    private AiQueryContext context;
    private Shop baseShop;
    private ShopType shopType;
    private List<Shop> candidates = new ArrayList<>();
    private List<String> compareAxes = new ArrayList<>();
    private List<String> highlights = new ArrayList<>();
    private String summary;
}
