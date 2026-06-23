package com.hmdp.dto.agent;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * Scene fit payload for review summaries.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class AgentSceneFitDTO {
    private String scene;
    private Double score;
    private String label;
    private List<String> reasons = new ArrayList<>();
}
