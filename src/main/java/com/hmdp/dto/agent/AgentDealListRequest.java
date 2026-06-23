package com.hmdp.dto.agent;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Request for get_deal_list.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class AgentDealListRequest {
    private Integer peopleCount;
    private Double budgetPerPerson;
    private String dealType;
    private Boolean onlyAvailable = Boolean.TRUE;
}
