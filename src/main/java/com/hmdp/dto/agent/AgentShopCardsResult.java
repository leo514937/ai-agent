package com.hmdp.dto.agent;

import com.fasterxml.jackson.databind.PropertyNamingStrategy;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * Payload for get_shop_cards.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
@JsonNaming(PropertyNamingStrategy.SnakeCaseStrategy.class)
public class AgentShopCardsResult {
    private String status = "empty";
    private List<AgentShopCardDTO> items = new ArrayList<>();
    private List<String> missingShopIds = new ArrayList<>();
    private List<String> warnings = new ArrayList<>();
    private AgentToolTraceDTO trace = new AgentToolTraceDTO();
}
