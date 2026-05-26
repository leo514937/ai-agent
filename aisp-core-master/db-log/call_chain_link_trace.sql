CREATE TABLE `chat_event_chain_link_trace`
(
    `id`                    BIGINT(20) UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
    `trace_id`              VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '对应场景',
    `chain_link_trace_json` LONGTEXT COMMENT '缓存值',
    `created_at`            DATETIME               DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间(ms)',
    `updated_at`            DATETIME               DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间(ms)',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uniq_trace_id` (`trace_id`)
    KEY `idx_created_at` (`created_at`),
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin AUTO_INCREMENT=0 COMMENT='Event调用链路Trace';