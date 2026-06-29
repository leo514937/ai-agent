package com.hmdp.dto.agent;

import com.fasterxml.jackson.databind.PropertyNamingStrategy;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
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
@JsonNaming(PropertyNamingStrategy.SnakeCaseStrategy.class)
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
