CREATE TABLE `knowledge_base`
(
    `unique_id`           varchar(36)   NOT NULL COMMENT '唯一个id',
    `knowledge_base_type` int(11) NOT NULL DEFAULT 0 COMMENT '0:个人知识库，1：公共知识库，4:公司内部知识库-同proto',
    `creator_user_id`     varchar(255)  NOT NULL DEFAULT '' COMMENT '所属用户userid',
    `knowledge_base_name` varchar(255)  NOT NULL DEFAULT '' COMMENT '知识库名称',
    `state`               int(11) NOT NULL DEFAULT 0 COMMENT '状态，0：正常, -1:删除',
    `knowledge_base_path` varchar(2048) NOT NULL DEFAULT '' COMMENT '知识库路径',
    `biz_group`           VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '业务方向',
    `created_at`          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at`          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`unique_id`),
    UNIQUE KEY `uniq_unique_id` (`unique_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4  COMMENT='知识库';

CREATE TABLE `knowledge_base_doc`
(
    `unique_id`          varchar(36)   NOT NULL COMMENT '唯一个id',
    `creator_user_id`    varchar(255)  NOT NULL DEFAULT '' COMMENT '所属用户userid',
    `knowledge_base_id`  varchar(36)   NOT NULL DEFAULT -1 COMMENT '所属知识库的id，对应knowledge_base表的id',
    `doc_name`           varchar(255)  NOT NULL DEFAULT '' COMMENT '文档名称',
    `state`              int(11) NOT NULL DEFAULT 0 COMMENT '状态，0：正常',
    `doc_path`           varchar(2048) NOT NULL DEFAULT '' COMMENT '文档地址',
    `doc_source_type`    int(11) NOT NULL DEFAULT 0 COMMENT '文档类型',
    `parsed_at`          DATETIME               DEFAULT CURRENT_TIMESTAMP COMMENT '解析完成(ms)',
    `parse_rule_version` int(11) NOT NULL DEFAULT 0 COMMENT '解析规则版本号',
    `created_at`         DATETIME               DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间(ms)',
    `updated_at`         DATETIME               DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间(ms)',
    PRIMARY KEY (`unique_id`),
    UNIQUE KEY `uniq_unique_id` (`unique_id`),
    KEY                  `idx_knowledge_base_id` (`knowledge_base_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT '知识库文档';

CREATE TABLE `knowledge_base_doc_v2`
(
    `id`                BIGINT(20)    UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    `knowledge_base_id` BIGINT(20)   NOT NULL DEFAULT 0 COMMENT '所属知识库的id，对应knowledge_base表的unique_id',
    `knowledge_base_type` int(11) NOT NULL DEFAULT 0 COMMENT '1:收藏，2:订阅，3:个人文件夹，4:公司内部知识库-同proto',
    `doc_id`            BIGINT(20)    NOT NULL DEFAULT 0 COMMENT '内容id',
    `doc_type`          VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '内容类型',
    `operator`          VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '操作人邮箱前缀',
    `created_at`        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at`        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uniq_base_and_doc` (`knowledge_base_id`, `knowledge_base_type`, `doc_id`, `doc_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin COMMENT='知识库文档关联表';

CREATE TABLE `knowledge_base_chunk`
(
    `id`                 BIGINT NOT NULL COMMENT '主键ID',
    `chunk_text`         TEXT COMMENT '文本内容',
    `doc_id`             VARCHAR(36) NOT NULL COMMENT '文档ID',
    `parse_rule_version` BIGINT NOT NULL DEFAULT 0 COMMENT '解析规则版本号',
    `created_at`         DATETIME        DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间(ms)',
    PRIMARY KEY (`id`),
    KEY                  `idx_doc_id_parse_rule_version` (`doc_id`, `parse_rule_version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin COMMENT='知识库chunk';


CREATE TABLE `document_parsing_base`
(
    `id`                BIGINT(20)    UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    `doc_id`            BIGINT(20)    NOT NULL DEFAULT 0 COMMENT '内容id',
    `doc_type`          VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '内容类型',
    `processor_type`    VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '解析器类型',
    `processor_name`    VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '解析器名称',
    `processor_version` VARCHAR(100)  NOT NULL DEFAULT '' COMMENT '解析器版本',
    `item_name`         VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '当前解析结果名称',
    `content`           TEXT          NOT NULL COMMENT '文本内容',
    `created_at`        DATETIME      DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间(ms)',
    `updated_at`        DATETIME      DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间(ms)',
    PRIMARY KEY (`id`),
    KEY              `idx_created_at` (`created_at`),
    KEY              `idx_processor` (`processor_name`),
    KEY              `idx_doc_id_and_type` (`doc_id`, `doc_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin AUTO_INCREMENT=0 COMMENT='文本精准解析结果库';


CREATE TABLE `document_info`
(
    `id`                BIGINT(20)    UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    `doc_id`            BIGINT(20)    NOT NULL DEFAULT 0 COMMENT '内容id',
    `doc_type`          VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '内容类型',
    `title`             VARCHAR(255)  NOT NULL DEFAULT '' COMMENT '标题',
    `abstract`          TEXT          COMMENT '摘要',
    `content`           TEXT          COMMENT '正文',
    `last_updated_time` BIGINT(20)    NOT NULL DEFAULT 0 COMMENT '文档最后更新时间，秒级时间戳',
    `url`               VARCHAR(512)  NOT NULL DEFAULT '' COMMENT 'url',
    `tags`              TEXT          COMMENT '标签，逗号分隔',
    `authority_level`   VARCHAR(8)    NOT NULL DEFAULT '' COMMENT '权威性等级',
    `doc_source`        VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '来源，如wiki、kdoc',
    `biz_group`         VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '业务方向',
    `operator`          VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '操作人邮箱前缀',
    `created_at`        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at`        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    KEY              `idx_created_at` (`created_at`),
    KEY              `idx_url` (`url`),
    UNIQUE KEY       `uniq_doc_id_and_type` (`doc_id`, `doc_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin AUTO_INCREMENT=0 COMMENT='文本信息库';