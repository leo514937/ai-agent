package com.hmdp.controller;


import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.hmdp.dto.Result;
import com.hmdp.entity.Shop;
import com.hmdp.service.IShopService;
import com.hmdp.utils.SystemConstants;
import org.springframework.web.bind.annotation.*;

import javax.annotation.Resource;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * <p>
 * 前端控制器
 * </p>
 *
 * @author 虎哥
 * @since 2021-12-22
 */
@RestController
@RequestMapping("/shop")
public class ShopController {

    @Resource
    public IShopService shopService;

    /**
     * 根据id查询商铺信息
     * @param id 商铺id
     * @return 商铺详情数据
     */
    @GetMapping("/{id}")
    public Result queryShopById(@PathVariable("id") Long id) {
        return shopService.queryById(id);
    }

    /**
     * 新增商铺信息
     * @param shop 商铺数据
     * @return 商铺id
     */
    @PostMapping
    public Result saveShop(@RequestBody Shop shop) {
        // 写入数据库
        shopService.save(shop);
        // 返回店铺id
        return Result.ok(shop.getId());
    }

    /**
     * 更新商铺信息
     * @param shop 商铺数据
     * @return 无
     */
    @PutMapping
    public Result updateShop(@RequestBody Shop shop) {
        // 写入数据库
        return shopService.update(shop);
    }

    /**
     * 根据商铺类型分页查询商铺信息
     * @param typeId 商铺类型
     * @param current 页码
     * @return 商铺列表
     */
    @GetMapping("/of/type")
    public Result queryShopByType(
            @RequestParam("typeId") Integer typeId,
            @RequestParam(value = "current", defaultValue = "1") Integer current,
            @RequestParam(value = "x",required = false) Double x,
            @RequestParam(value = "y",required = false) Double y
    ) {
        return shopService.queryShopById(typeId,current,x,y);
    }

    /**
     * 根据商铺名称关键字分页查询商铺信息
     * @param name 商铺名称关键字
     * @param current 页码
     * @return 商铺列表
     */
    @GetMapping("/of/name")
    public Result queryShopByName(
            @RequestParam(value = "name", required = false) String name,
            @RequestParam(value = "current", defaultValue = "1") Integer current
    ) {
        // 根据类型分页查询
        Page<Shop> page = shopService.query()
                .like(StrUtil.isNotBlank(name), "name", name)
                .page(new Page<>(current, SystemConstants.MAX_PAGE_SIZE));
        // 返回数据
        return Result.ok(page.getRecords());
    }

    /**
     * 多参数组合查询商铺（支持品牌+区域+类型任意组合）
     * @param name 商铺名称关键字（可选，LIKE匹配）
     * @param area 商圈/区域关键字（可选，LIKE匹配）
     * @param typeId 商铺类型ID（可选，精确匹配）
     * @param current 页码
     * @return 商铺列表
     */
    @GetMapping("/search")
    public Result searchShops(
            @RequestParam(value = "name", required = false) String name,
            @RequestParam(value = "area", required = false) String area,
            @RequestParam(value = "typeId", required = false) Integer typeId,
            @RequestParam(value = "current", defaultValue = "1") Integer current
    ) {
        Page<Shop> page = shopService.query()
                .like(StrUtil.isNotBlank(name), "name", name)
                .like(StrUtil.isNotBlank(area), "area", area)
                .eq(typeId != null, "type_id", typeId)
                .orderByDesc("score")
                .page(new Page<>(current, SystemConstants.MAX_PAGE_SIZE));
        return Result.ok(page.getRecords());
    }

    /**
     * 获取所有不重复的品牌名称（从店铺名称中提取首段作为品牌）
     * @return 品牌名称列表
     */
    @GetMapping("/brands")
    public Result listBrands() {
        List<Shop> allShops = shopService.query().list();
        Set<String> brands = new LinkedHashSet<>();
        for (Shop shop : allShops) {
            String name = shop.getName();
            if (StrUtil.isNotBlank(name)) {
                // 提取品牌：取名称中括号前的部分，再去掉"店"等后缀
                String brand = name;
                int bracketIdx = name.indexOf('(');
                if (bracketIdx < 0) bracketIdx = name.indexOf('（');
                if (bracketIdx > 0) {
                    brand = name.substring(0, bracketIdx);
                }
                brand = brand.replaceAll("(店|餐厅|火锅|料理|菜)$", "").trim();
                if (StrUtil.isNotBlank(brand)) {
                    brands.add(brand);
                }
            }
        }
        return Result.ok(new ArrayList<>(brands));
    }

    /**
     * 获取所有不重复的区域/商圈名称
     * @return 区域名称列表
     */
    @GetMapping("/areas")
    public Result listAreas() {
        List<Shop> allShops = shopService.query().list();
        Set<String> areas = new LinkedHashSet<>();
        for (Shop shop : allShops) {
            String area = shop.getArea();
            if (StrUtil.isNotBlank(area)) {
                areas.add(area.trim());
            }
        }
        return Result.ok(new ArrayList<>(areas));
    }
}
