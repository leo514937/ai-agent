CREATE TABLE `word_mapper` (
   `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT COMMENT '主键',
   `word_id` bigint(20) unsigned NOT NULL DEFAULT 0 COMMENT '词主键（混淆）',
   `word_type` int NOT NULL DEFAULT 0 COMMENT '词类型',
   `word` varchar(100) NOT NULL DEFAULT '' COMMENT '词',
   `source_id` varchar(100) NOT NULL DEFAULT '' COMMENT '原始词Id 用于记录来源自搜索词库词的原始Id',
   `deleted` int NOT NULL DEFAULT 0 COMMENT '逻辑删除 否:0 是:1',
   `created_at` timestamp DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间(ms)',
   `updated_at` timestamp DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间(ms)',
   PRIMARY KEY (`id`),
   UNIQUE INDEX `uniq_type_and_word` (`word_type`, `word`),
   INDEX `idx_type_and_word_id` (`word_type`, `word_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin AUTO_INCREMENT=0 COMMENT='词映射表-用于AI-Tab/搜索Tab';

CREATE TABLE `prompt_mapper` (
   `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT COMMENT '主键',
   `prompt_code` varchar(100) NOT NULL DEFAULT '' COMMENT 'prompt 编号',
   `prompt` text NOT NULL COMMENT 'prompt',
   `remark` varchar(100) NOT NULL DEFAULT '' COMMENT '备注',
   `created_at` timestamp DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间(ms)',
   `updated_at` timestamp DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间(ms)',
   PRIMARY KEY (`id`),
   UNIQUE KEY `uniq_prompt_code` (`prompt_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin AUTO_INCREMENT=0 COMMENT='prompt 映射关系表';


-- 消息会话记录表
CREATE TABLE `dialog_record` (
     `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT COMMENT '主键',
     `role_type` varchar(50) NOT NULL DEFAULT '' COMMENT '角色类型 USER AI',
     `scene` varchar(50) NOT NULL DEFAULT '' COMMENT '场景 AI_TAB SEARCH_TAB',
     `member_id` bigint(20) unsigned NOT NULL DEFAULT 0 COMMENT '用户Id',
     `ai_id` bigint(20) unsigned NOT NULL DEFAULT 0 COMMENT 'AI Id',
     `session_id` bigint(20) unsigned NOT NULL DEFAULT 0 COMMENT '会话Id',
     `conversation_id`   varchar(255) NOT NULL DEFAULT '' COMMENT '对话ID',
     `message_id` varchar(255) NOT NULL DEFAULT '' COMMENT '消息Id',
     `parent_message_id` varchar(255) NOT NULL DEFAULT '' COMMENT '父级消息Id',
     `message` text NOT NULL COMMENT '消息 JSON',
     `message_content` text NOT NULL COMMENT '消息文本 当消息类型为文本时有效',
     `message_type` int NOT NULL DEFAULT 0 COMMENT '消息类型 0:未知 1:文本',
     `record_at` timestamp DEFAULT 0 COMMENT '消息记录时间(ms)',
     `create_type` int NOT NULL DEFAULT 0 COMMENT '创建类型 0未知 1:用户输入 2:静态库输出 3:LLM输出',
     `error_type` int NOT NULL DEFAULT 0 COMMENT '异常类型 0正常 1:系统异常 2:安全拒答 3:安全兜底 4:LLM兜底',
     `deleted` int NOT NULL DEFAULT 0 COMMENT '逻辑删除 否:0 是:1',
     `created_at` timestamp DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间(ms)',
     `updated_at` timestamp DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间(ms)',
     PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin AUTO_INCREMENT=0 COMMENT='消息会话记录表';

create unique index idx_session_message
    on dialog_record (`session_id`, `message_id`)
    comment 'Session与MessageId唯一';
create index idx_session_created_at
    on dialog_record (`session_id`, `created_at`)
    comment 'Session与Created排序';
create index idx_member_created_at
    on dialog_record (`member_id`, `created_at`)
    comment 'Member与Created排序';


-- 消息会话记录表
CREATE TABLE `dialog_session` (
     `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT COMMENT '主键',
     `scene` varchar(50) NOT NULL DEFAULT '' COMMENT '场景 AI_TAB SEARCH_TAB',
     `member_id` bigint(20) unsigned NOT NULL DEFAULT 0 COMMENT '用户Id',
     `session_id` bigint(20) unsigned NOT NULL DEFAULT 0 COMMENT '会话Id',
     `extra_info` text NOT NULL COMMENT '附加信息',
     `deleted` int NOT NULL DEFAULT 0 COMMENT '逻辑删除 否:0 是:1',
     `created_at` timestamp DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间(ms)',
     `updated_at` timestamp DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间(ms)',
     PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin AUTO_INCREMENT=0 COMMENT='消息会话记录表';
create unique index idx_session
    on dialog_record (`session_id`)
    comment 'Session唯一';


-- 算子 session 维度缓存
CREATE TABLE `logic_session_cache` (
      `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT COMMENT '主键',
      `cache_key` varchar(255) NOT NULL DEFAULT '' COMMENT '缓存Key',
      `cache_value` LONGTEXT COMMENT '缓存值',
      `expire_time` timestamp NOT NULL COMMENT '过期时间(ms)',
      `created_at` timestamp DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间(ms)',
      `updated_at` timestamp DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间(ms)',
      PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin AUTO_INCREMENT=0 COMMENT='消息会话记录表';
create unique index uniq_logic_cache_key
    on logic_session_cache (`cache_key`)
    comment 'Session唯一';

-- 2024年06月21日16:16:03
alter table dialog_record
    add `message_group_id` varchar(255) NOT NULL DEFAULT '' COMMENT '消息组Id（默认为message_id）' after conversation_id;
alter table dialog_record
    add `exceeded` int NOT NULL DEFAULT 0 COMMENT '是否过期 否:0 是:1' after error_type;
create index idx_session_group_id
    on dialog_record (`session_id`, `message_group_id`)
    comment 'Session与message_group_id用于重答';