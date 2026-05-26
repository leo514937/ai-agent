CREATE TABLE `knowledge_base_v2`
(
    `id`                BIGINT(20) UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    `scene`             VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '对应场景',
    `key_words`         VARCHAR(1000) NOT NULL DEFAULT '' COMMENT '多个关键词,「;」分割',
    `knowledge_content` TEXT          NOT NULL COMMENT '知识内容',
    `create_user_id`    VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '创建者',
    `update_user_id`    VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '更新者',
    `status_code`       TINYINT       NOT NULL DEFAULT 0 COMMENT '状态。0：初始化状态，1：未上线，2：已上线，3：已删除',
    `created_at`        DATETIME               DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间(ms)',
    `updated_at`        DATETIME               DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间(ms)',
    PRIMARY KEY (`id`),
    KEY                 `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin AUTO_INCREMENT=0 COMMENT='知识库';


CREATE TABLE `static_base`
(
    `id`                      BIGINT(20) UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    `scene`                   VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '对应场景',
    `question`                VARCHAR(1000) NOT NULL DEFAULT '' COMMENT '问题',
    `answer`                  TEXT          NOT NULL COMMENT '答案',
    `no_symbol_question_hash` BIGINT(20) NOT NULL DEFAULT 0 COMMENT '去除符号后的问题的hash值',
    `create_user_id`          VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '创建者',
    `update_user_id`          VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '更新者',
    `status_code`             TINYINT       NOT NULL DEFAULT 0 COMMENT '状态。0：初始化状态，1：未上线，2：已上线，3：已删除',
    `created_at`              DATETIME               DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间(ms)',
    `updated_at`              DATETIME               DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间(ms)',
    PRIMARY KEY (`id`),
    KEY                       `idx_created_at` (`created_at`),
    KEY                       `idx_no_symbol_question_hash` (`no_symbol_question_hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin AUTO_INCREMENT=0 COMMENT='静态库';

CREATE TABLE `faq_base`
(
    `id`             BIGINT(20) UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    `scene`          VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '对应场景',
    `question`       VARCHAR(1000) NOT NULL DEFAULT '' COMMENT '问题',
    `answer`         TEXT          NOT NULL COMMENT '答案',
    `match_type`     BIGINT(20) NOT NULL DEFAULT 0 COMMENT '匹配方式。可以多选，bit占位',
    `create_user_id` VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '创建者',
    `update_user_id` VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '更新者',
    `status_code`    TINYINT       NOT NULL DEFAULT 0 COMMENT '状态。0：初始化状态，1：未上线，2：已上线，3：已删除',
    `show_recall`    TINYINT       NOT NULL DEFAULT 0 COMMENT '命中faq时是否展示召回。0：不展示，1：展示',
    `created_at`     DATETIME               DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间(ms)',
    `updated_at`     DATETIME               DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间(ms)',
    PRIMARY KEY (`id`),
    KEY              `idx_created_at` (`created_at`),
    KEY              `idx_match_type` (`match_type`),
    KEY              `idx_scene` (`scene`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin AUTO_INCREMENT=0 COMMENT='faq库';