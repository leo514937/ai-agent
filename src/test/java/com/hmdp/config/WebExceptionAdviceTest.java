package com.hmdp.config;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.context.request.async.AsyncRequestTimeoutException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

class WebExceptionAdviceTest {

    @Test
    void shouldHandleAsyncRequestTimeoutWithoutWritingJsonBody() {
        WebExceptionAdvice advice = new WebExceptionAdvice();

        ResponseEntity<Void> response = advice.handleAsyncRequestTimeoutException(new AsyncRequestTimeoutException());

        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, response.getStatusCode());
        assertNull(response.getBody());
    }
}
