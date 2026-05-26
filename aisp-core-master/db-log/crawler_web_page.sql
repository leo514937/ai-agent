-- oceanbase数据库
CREATE TABLE `crawler_web_page`
(
    `doc_id`             bigint        not null default 0 COMMENT '内容id',
    `doc_type`           VARCHAR(64)   not null default '' COMMENT '内容类型',
    `object_id`          VARCHAR(256)  not null default '' COMMENT 'object_id',
    `title`              VARCHAR(2048) not null default '' COMMENT '网站标题',
    `meta_url`           VARCHAR(2048) not null default '' COMMENT 'url',
    `source`             VARCHAR(64)   not null default '' COMMENT '网站名字',
    `source_level`       int           not null default 0 COMMENT '网站等级',
    `content`            TEXT COMMENT   '网站内容，无html标签',
    `domain`             VARCHAR(64)   not null default '' COMMENT '网站领域',
    `publish_time`       bigint        not null default 0 COMMENT '网页发布时间',
    `is_crawler_allowed` int COMMENT '网页是否允许被爬，0: 不允许，1：允许',
    `crawler_time`       bigint        not null default 0 COMMENT '秒级时间戳',
    `extra_info`         TEXT COMMENT   '额外信息',
    `created_at`         DATETIME               DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间(ms)',
    `updated_at`         DATETIME               DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间(ms)',
    primary KEY `idx_doc_id_doc_type` (`doc_id`, `doc_type`)
) COMMENT '爬取的站外网页'
PARTITION BY KEY(doc_id)
PARTITIONS 128;