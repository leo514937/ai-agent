package com.hmdp.ai.remote;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.LinkedHashMap;
import java.util.Map;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class AiRemoteStreamEvent {

    /**
     * SSE 的 event 字段。
     */
    private String event;

    /**
     * SSE 的 id 字段。
     */
    private String id;

    /**
     * SSE 原始 data 字段。
     */
    private String data;

    /**
     * 将 data 解析后的结构化内容，兼容不同返回协议。
     */
    private Map<String, Object> payload = new LinkedHashMap<>();
}
