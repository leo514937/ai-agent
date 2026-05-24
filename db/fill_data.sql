-- 1. 补全秒杀优惠券数据
-- 先添加一张类型为 1 (秒杀券) 的代金券
INSERT INTO `tb_voucher` (`id`, `shop_id`, `title`, `sub_title`, `rules`, `pay_value`, `actual_value`, `type`, `status`) 
VALUES (2, 1, '100元代金券', '周一至周日均可使用', '全场通用\n无需预约\n可无限叠加\n不兑现、不找零\n仅限堂食', 8000, 10000, 1, 1);

-- 在秒杀表中设置该券的库存 (100张) 和有效期 (从现在起一个月)
INSERT INTO `tb_seckill_voucher` (`voucher_id`, `stock`, `begin_time`, `end_time`) 
VALUES (2, 100, NOW(), DATE_ADD(NOW(), INTERVAL 30 DAY));


-- 2. 补全用户信息扩展表 (为前几个活跃用户添加资料)
INSERT INTO `tb_user_info` (`user_id`, `city`, `introduce`, `fans`, `followee`, `gender`, `birthday`, `credits`) VALUES 
(1, '杭州', '一棵开花的树', 100, 20, 0, '1995-05-20', 1000),
(2, '上海', '今天也要加油鸭', 50, 10, 1, '1998-08-08', 500),
(4, '北京', '代码改变世界', 200, 50, 0, '1990-01-01', 2000),
(5, '深圳', '爱生活，爱点评', 30, 5, 1, '2000-12-12', 300);


-- 3. 预置一些关注关系 (用于测试关注/取关及共同关注功能)
INSERT INTO `tb_follow` (`user_id`, `follow_user_id`) VALUES 
(1, 2), 
(1, 4), 
(2, 1),
(4, 1);
