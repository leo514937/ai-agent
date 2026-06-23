package com.hmdp.dto.agent;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * Structured deal / group-buy item.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class AgentDealDTO {
    private String dealId;
    private String title;
    private String dealType;
    private Double price;
    private Double originalPrice;
    private Double discountRate;
    private Integer peopleCountMin;
    private Integer peopleCountMax;
    private Double avgPricePerPerson;
    private Boolean available;
    private String validTimeText;
    private List<String> useTimeRules = new ArrayList<>();
    private List<String> limitations = new ArrayList<>();
    private List<String> includedItems = new ArrayList<>();
    private List<String> recommendTags = new ArrayList<>();
    private List<String> sourceFields = new ArrayList<>();
}
