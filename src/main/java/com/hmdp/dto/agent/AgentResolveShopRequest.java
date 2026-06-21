package com.hmdp.dto.agent;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * Request for resolve_shop tool.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class AgentResolveShopRequest {
    private String query;
    private AgentLocation location;
    private List<String> sessionShopIds;
}
