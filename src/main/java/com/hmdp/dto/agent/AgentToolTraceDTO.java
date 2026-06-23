package com.hmdp.dto.agent;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Shared trace payload for agent query tools.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class AgentToolTraceDTO {
    private String toolName;
    private String backendSource = "java_api";
    private Long durationMs;
    private Map<String, Object> input;
    private String status;
    private Integer itemCount;
    private List<String> missingShopIds = new ArrayList<>();
    private List<String> warnings = new ArrayList<>();
    private String errorType;
    private String errorMessage;
}
