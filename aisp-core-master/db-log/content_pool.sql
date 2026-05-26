CREATE TABLE `crawled_web_page`
(
    `id`           BIGINT(20) UNSIGNED NOT NULL AUTO_RANDOM COMMENT '主键',
    `p_date`       VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '数据的日期。格式为2006-01-02',
    `query_merge`  VARCHAR(1000) NOT NULL DEFAULT '' COMMENT 'query merge',
    `member_id`    BIGINT        NOT NULL DEFAULT 0 COMMENT 'member_id',
    `scene`        VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '匹配方式。可以多选，bit占位',
    `publish_time` BIGINT        NOT NULL DEFAULT 0 COMMENT '网页发布时间，单位秒',
    `url`          VARCHAR(1024) NOT NULL DEFAULT '' COMMENT 'url',
    `url_hash`     BIGINT        NOT NULL DEFAULT 0 COMMENT 'url hash值',
    `content`      TEXT COMMENT '网页爬取的文本内容',
    `title`        VARCHAR(1024) NOT NULL DEFAULT '' COMMENT '网页title',
    `crawl_at`     DATETIME DEFAULT '1970-01-01' COMMENT '网页爬取的时间',
    PRIMARY KEY (`id`),
    KEY            `idx_url_hash` (`url_hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin AUTO_INCREMENT=0 COMMENT='爬虫网页信息';