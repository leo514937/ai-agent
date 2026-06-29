package com.hmdp.dto.agent;

import com.fasterxml.jackson.databind.PropertyNamingStrategy;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * Payload for get_deal_list.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
@JsonNaming(PropertyNamingStrategy.SnakeCaseStrategy.class)
public class AgentDealListResult {
    private String status = "empty";
    private String shopId = "";
    private String shopName;
    private List<AgentDealDTO> items = new ArrayList<>();
    private List<String> warnings = new ArrayList<>();
    private AgentToolTraceDTO trace = new AgentToolTraceDTO();
}
