package com.hmdp.ai.remote;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AiRemoteStreamParserTest {

    @Test
    void shouldParseFinalSseEvent() throws Exception {
        AiRemoteStreamParser parser = new AiRemoteStreamParser();
        ReflectionTestUtils.setField(parser, "objectMapper", new ObjectMapper());

        String raw = "event: ack\n" +
                "data: {\"event_type\":\"ack\",\"trace_id\":\"trace-1\",\"session_id\":\"session-1\",\"turn_id\":\"turn-1\",\"workflow_version\":\"learn-agent/v1\",\"payload\":{\"message\":\"accepted\"}}\n\n" +
                "event: final\n" +
                "data: {\"event_type\":\"final\",\"trace_id\":\"trace-1\",\"session_id\":\"session-1\",\"turn_id\":\"turn-1\",\"workflow_version\":\"learn-agent/v1\",\"payload\":{\"answer_text\":\"你好，已经帮你查到结果了\",\"mode\":\"recommend\",\"source\":\"learning-agent-service\",\"page\":\"meituan_search_box\",\"current_topic\":\"火锅\",\"next_steps\":[\"查看第一家详情\",\"看优惠券\"],\"task_chain\":[{\"step\":\"search\",\"label\":\"已完成候选店搜索\",\"status\":\"done\"}],\"suggested_replies\":[{\"label\":\"看第二家\",\"prompt\":\"看第二家\"}],\"shops\":[{\"id\":101,\"name\":\"火锅店\"}],\"vouchers\":[{\"id\":201,\"shopId\":101,\"title\":\"满100减20\"}]}}\n\n";

        AiRemoteChatResult result = parser.parse(new ByteArrayInputStream(raw.getBytes(StandardCharsets.UTF_8)));

        assertTrue(result.isSuccess());
        assertEquals("你好，已经帮你查到结果了", result.getAnswer());
        assertEquals("recommend", result.getMode());
        assertEquals("learning-agent-service", result.getSource());
        assertEquals("火锅", result.getCurrentTopic());
        assertEquals("meituan_search_box", result.getPage());
        assertEquals(2, ((java.util.List<?>) result.getMetadata().get("next_steps")).size());
        assertEquals(1, ((java.util.List<?>) result.getMetadata().get("task_chain")).size());
    }
}
