package com.hmdp.ai.remote;

import cn.hutool.core.util.StrUtil;
import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Data
@Component
@ConfigurationProperties(prefix = "ai.remote")
public class AiRemoteProperties {

    /**
     * 是否启用远端 learning-agent-service。
     */
    private boolean enabled = false;

    /**
     * 远端服务基础地址，例如 http://127.0.0.1:8000。
     */
    private String baseUrl;

    /**
     * 远端服务内部鉴权 token。
     */
    private String internalToken;

    public boolean isAvailable() {
        return enabled && StrUtil.isNotBlank(resolveBaseUrl());
    }

    public String resolveBaseUrl() {
        return StrUtil.isBlank(baseUrl) ? null : StrUtil.removeSuffix(baseUrl.trim(), "/");
    }
}
