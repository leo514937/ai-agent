-- Verify seed data (Phase 4 integration check)
SELECT '1. Seed shop count' AS check_name, COUNT(*) AS value FROM tb_shop WHERE id >= 900001;
SELECT '2. Seed voucher count' AS check_name, COUNT(*) AS value FROM tb_voucher WHERE id >= 910001;

SELECT '3. resolve_shop(海底捞)' AS check_name, id, name, area, score FROM tb_shop WHERE name LIKE '%海底捞%' LIMIT 5;
SELECT '4. search_shops(咖啡)' AS check_name, id, name, area, score FROM tb_shop WHERE name LIKE '%咖啡%' LIMIT 5;

SELECT '5. get_shop_detail(900001)' AS check_name, id, name, type_id, area, address, x, y, avg_price, score, open_hours FROM tb_shop WHERE id = 900001;

SELECT '6. get_coupon_list(900002)' AS check_name, id, title, pay_value, actual_value, type, status FROM tb_voucher WHERE shop_id = 900002;

SELECT '7a. Rollback would delete shops' AS check_name, COUNT(*) AS value FROM tb_shop WHERE id BETWEEN 900001 AND 900027;
SELECT '7b. Rollback would delete vouchers' AS check_name, COUNT(*) AS value FROM tb_voucher WHERE id BETWEEN 910001 AND 910016;

SELECT '8a. Original shops intact' AS check_name, COUNT(*) AS value FROM tb_shop WHERE id <= 22;
SELECT '8b. Original vouchers intact' AS check_name, COUNT(*) AS value FROM tb_voucher WHERE id <= 9;

SELECT '9. Score range' AS check_name, MIN(score) AS min_score, MAX(score) AS max_score FROM tb_shop WHERE id BETWEEN 900001 AND 900027;

SELECT '10. Orphan vouchers' AS check_name, COUNT(*) AS value FROM tb_voucher v LEFT JOIN tb_shop s ON v.shop_id = s.id WHERE v.id BETWEEN 910001 AND 910016 AND s.id IS NULL;
