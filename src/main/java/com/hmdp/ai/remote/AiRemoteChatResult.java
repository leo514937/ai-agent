package com.hmdp.ai.remote;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class AiRemoteChatResult {

    /**
     * 远端调用是否成功拿到可用结果。
     */
    private boolean success;

    /**
     * 是否建议调用方回退到本地兜底逻辑。
     */
    private boolean fallbackSuggested;

    private String answer;
    private String mode;
    private String source;
    private String page;
    private String currentTopic;
    private String sessionId;
    private String traceId;
    private String finishReason;
    private String finalEvent;
    private String errorMessage;
    private String rawResponse;

    private Map<String, Object> metadata = new LinkedHashMap<>();
    private List<AiRemoteStreamEvent> events = new ArrayList<>();

    public static AiRemoteChatResult failure(String errorMessage) {
        AiRemoteChatResult result = new AiRemoteChatResult();
        result.setSuccess(false);
        result.setFallbackSuggested(true);
        result.setErrorMessage(errorMessage);
        return result;
    }
}
