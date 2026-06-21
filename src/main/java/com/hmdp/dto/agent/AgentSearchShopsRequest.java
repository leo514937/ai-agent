package com.hmdp.dto.agent;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Request for search_shops tool.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class AgentSearchShopsRequest {
    private String query;
    private String category;
    private Integer limit = 20;
    private AgentLocation location;
}
