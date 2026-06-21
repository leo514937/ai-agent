SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- Rollback seed data
-- Delete vouchers first (child table), then shops (parent table)
-- Voucher ID range: 910001–910016
DELETE FROM `tb_voucher` WHERE `id` BETWEEN 910001 AND 910016;

-- Shop ID range: 900001–900027
DELETE FROM `tb_shop` WHERE `id` BETWEEN 900001 AND 900027;


SET FOREIGN_KEY_CHECKS = 1;
