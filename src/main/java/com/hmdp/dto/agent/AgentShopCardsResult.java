package com.hmdp.dto.agent;

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
public class AgentShopCardsResult {
    private String status = "empty";
    private List<AgentShopCardDTO> items = new ArrayList<>();
    private List<String> missingShopIds = new ArrayList<>();
    private List<String> warnings = new ArrayList<>();
    private AgentToolTraceDTO trace = new AgentToolTraceDTO();
}
