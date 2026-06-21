package com.hmdp.dto.agent;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Location coordinates for agent requests.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class AgentLocation {
    private Double lat;
    private Double lng;
}
