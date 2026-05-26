CREATE TABLE `badcase_tracing_list`
(
    `id`                  BIGINT(20) UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    `member_id`           BIGINT(20) NOT NULL DEFAULT 0 COMMENT '用户id',
    `chat_scene`          VARCHAR(64) NOT NULL DEFAULT '' COMMENT '对话场景',
    `chat_sub_scene`      VARCHAR(64) NOT NULL DEFAULT '' COMMENT '对话子场景',
    `request_message_id`  VARCHAR(64) NOT NULL DEFAULT '' COMMENT '请求消息id',
    `request_query`       TEXT COMMENT '请求内容',
    `response_message_id` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '返回消息id',
    `response_answer`     TEXT COMMENT '模型回答',
    `trace_id`            VARCHAR(64) NOT NULL DEFAULT '' COMMENT '透传traceId',
    `feedback_source`     VARCHAR(64) NOT NULL DEFAULT '' COMMENT '反馈来源',
    `case_type`           VARCHAR(64) NOT NULL DEFAULT '' COMMENT '反馈case类型',
    `handling_state`      VARCHAR(24) NOT NULL DEFAULT '' COMMENT '处理状态',
    `handling_member`     VARCHAR(64) NOT NULL DEFAULT '' COMMENT '处理人',
    `handling_result`     TEXT COMMENT '处理结果描述',
    `state`               TINYINT     NOT NULL DEFAULT 1 COMMENT '有效状态，0：已删除，1：正常，2：同步中',
    `created_at`          DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at`          DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    KEY                   `idx_trace_id` (`trace_id`),
    KEY                   `idx_member_id` (`member_id`),
    KEY                   `idx_message_id` (`request_message_id`),
    KEY                   `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin COMMENT='badcase 列表';

CREATE TABLE `badcase_tracing_process`
(
    `id`           BIGINT(20) UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    `trace_id`     VARCHAR(64) NOT NULL DEFAULT '' COMMENT '透传traceId',
    `query_router` TEXT COMMENT 'query路由',
    `query_merge`  TEXT COMMENT 'query合并',
    `recalls`      TEXT COMMENT '召回docs',
    `cards`        text comment '参考文献卡片',
    `reranks`      TEXT COMMENT '重排chunks',
    `summary`      TEXT COMMENT '模型回答',
    `securities`   VARCHAR(64) not null DEFAULT '' comment '安全、faq、红线必答命中情况',
    `created_at`   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at`   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    KEY            `idx_trace_id` (`trace_id`),
    KEY            `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin COMMENT='badcase 中间过程';