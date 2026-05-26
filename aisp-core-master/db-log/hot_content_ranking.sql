CREATE TABLE `hot_extract_products_ranking_evaluation`
(
    `id`                       BIGINT(20) UNSIGNED NOT NULL AUTO_RANDOM COMMENT '主键' primary key,
    `bayes_firstcategory_name` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '贝叶斯一级',
    `first_level_top`          VARCHAR(255) NOT NULL DEFAULT '' COMMENT '一级层级第一个',
    `second_level_top`         VARCHAR(255) NOT NULL DEFAULT '' COMMENT '二级层级第一个',
    `evaluation_list_json`     TEXT COMMENT '评价统计',
    `entity_name`              VARCHAR(255) NOT NULL DEFAULT '' COMMENT '实体名称',
    `entity_score`             BIGINT       NOT NULL DEFAULT 0 COMMENT '实体分数',
    `entity_rank`              BIGINT       NOT NULL DEFAULT 0 COMMENT '实体排名',
    `p_date`                   VARCHAR(255) NOT NULL DEFAULT '' COMMENT '分区yyyy-MM-dd',
    `created_at`               DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间(ms)',
    `updated_at`               DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间(ms)',
    KEY                        `idx_p_date_bayes_firstcategory_name` (`p_date`, `bayes_firstcategory_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT '商品热度分数表';


CREATE TABLE `hot_content_products_synonym`
(
    `id`                        BIGINT(20) UNSIGNED NOT NULL AUTO_RANDOM COMMENT '主键' primary key,
    `bayes_first_category_name` varchar(255)  NOT NULL DEFAULT '' COMMENT '一级贝叶斯领域',
    `take_effect_field`         varchar(255)  NOT NULL DEFAULT '' COMMENT '生效字段',
    `keyword`                   varchar(255)  NOT NULL DEFAULT '' COMMENT '关键词',
    `synonyms`                  varchar(1024) NOT NULL DEFAULT '' COMMENT '同义词列表，「;」分隔',
    `create_user_id`            VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '创建者',
    `update_user_id`            VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '更新者',
    `status_code`               TINYINT       NOT NULL DEFAULT 0 COMMENT '状态。0：初始化状态，1：未上线，2：已上线，3：已删除',
    `created_at`                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间(ms)',
    `updated_at`                DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间(ms)'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT '热门内容同义词表';
