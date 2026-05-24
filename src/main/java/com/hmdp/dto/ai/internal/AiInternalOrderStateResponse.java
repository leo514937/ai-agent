package com.hmdp.dto.ai.internal;

import lombok.Data;

@Data
public class AiInternalOrderStateResponse {
    private Long orderId;
    private boolean found;
    private String code;
    private String message;
    private String status;
    private Long voucherId;
    private Long userId;
}
