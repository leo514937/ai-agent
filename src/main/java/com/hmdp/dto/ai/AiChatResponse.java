package com.hmdp.dto.ai;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class AiChatResponse {
    private String answer;
    private String mode;
    private String source;
    private boolean fallback;
    private String page;
    private String currentTopic;
    private List<AiChatSuggestion> suggestions = new ArrayList<>();
    private List<AiShopCard> shops = new ArrayList<>();
    private List<AiVoucherCard> vouchers = new ArrayList<>();
    private List<Map<String, Object>> cards = new ArrayList<>();
    private List<String> nextSteps = new ArrayList<>();
    private List<Map<String, Object>> taskChain = new ArrayList<>();
    private Map<String, Object> context = new LinkedHashMap<>();
}
