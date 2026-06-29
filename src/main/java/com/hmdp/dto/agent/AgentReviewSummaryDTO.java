package com.hmdp.dto.agent;

import com.fasterxml.jackson.databind.PropertyNamingStrategy;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
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
@JsonNaming(PropertyNamingStrategy.SnakeCaseStrategy.class)
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
