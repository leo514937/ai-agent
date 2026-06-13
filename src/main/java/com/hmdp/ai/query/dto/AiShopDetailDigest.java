package com.hmdp.ai.query.dto;

import com.hmdp.ai.query.AiQueryContext;
import com.hmdp.entity.Blog;
import com.hmdp.entity.Shop;
import com.hmdp.entity.ShopType;
import com.hmdp.entity.Voucher;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 店铺详情页的只读摘要数据。
 */
@Data
@NoArgsConstructor
public class AiShopDetailDigest {

    private AiQueryContext context;
    private Shop shop;
    private ShopType shopType;
    private List<Voucher> vouchers = new ArrayList<>();
    private List<Blog> blogs = new ArrayList<>();
    private AiUserContextDigest userContext;
    private Map<String, Object> knownConstraints = new LinkedHashMap<>();
    private List<String> comparisonTargets = new ArrayList<>();
    private String followUpKind;
    private List<String> highlights = new ArrayList<>();
    private String summary;
}
