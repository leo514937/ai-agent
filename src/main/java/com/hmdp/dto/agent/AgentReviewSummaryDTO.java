package com.hmdp.dto.agent;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * Structured review summary for a shop.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class AgentReviewSummaryDTO {
    private String shopId;
    private String name;
    private Double rating;
    private Integer reviewCount;
    private Double tasteScore;
    private Double environmentScore;
    private Double serviceScore;
    private Double priceScore;
    private List<String> positiveTags = new ArrayList<>();
    private List<String> negativeTags = new ArrayList<>();
    private List<String> sceneTags = new ArrayList<>();
    private AgentSceneFitDTO sceneFit = new AgentSceneFitDTO();
    private List<String> highlights = new ArrayList<>();
    private List<String> risks = new ArrayList<>();
    private String summary;
    private List<String> sourceFields = new ArrayList<>();
}
