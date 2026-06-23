package com.hmdp.dto.agent;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * Request for get_shop_review_summary.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class AgentReviewSummaryRequest {
    private List<String> shopIds = new ArrayList<>();
    private List<String> aspects = new ArrayList<>();
    private String scene;
    private Integer maxReviews;
}
