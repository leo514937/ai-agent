package com.hmdp.service;

/**
 * 远端 assistant 不可用且当前问题不适合本地业务兼容降级时抛出。
 */
public class AiAssistantUnavailableException extends RuntimeException {

    public AiAssistantUnavailableException(String message) {
        super(message);
    }
}
