package com.hmdp.dto.agent;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * Payload for get_shop_review_summary.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class AgentReviewSummaryResult {
    private String status = "empty";
    private List<AgentReviewSummaryDTO> items = new ArrayList<>();
    private List<String> missingShopIds = new ArrayList<>();
    private List<String> warnings = new ArrayList<>();
    private AgentToolTraceDTO trace = new AgentToolTraceDTO();
}
