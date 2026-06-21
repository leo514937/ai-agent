package com.hmdp.dto.agent;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Request for get_distance_eta tool.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class AgentDistanceEtaRequest {
    private Long shopId;
    private AgentLocation location;
}
