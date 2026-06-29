package com.hmdp.dto.agent;

import com.fasterxml.jackson.databind.PropertyNamingStrategy;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Request for check_open_status tool.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
@JsonNaming(PropertyNamingStrategy.SnakeCaseStrategy.class)
public class AgentOpenStatusRequest {
    private Long shopId;
    private String now;  // ISO datetime string, e.g. "2026-06-21T15:00:00"
}
