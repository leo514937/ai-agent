package com.hmdp.dto.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class AgentProtocolContractTest {

    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void distanceEtaRequestBindsFromLocation() throws Exception {
        String json = "{\"shop_id\":123,\"from_location\":{\"lat\":39.96,\"lng\":116.35}}";

        AgentDistanceEtaRequest request = mapper.readValue(json, AgentDistanceEtaRequest.class);

        assertEquals(123L, request.getShopId());
        assertNotNull(request.getFromLocation());
        assertEquals(39.96, request.getFromLocation().getLat(), 1e-6);
        assertEquals(116.35, request.getFromLocation().getLng(), 1e-6);

        String serialized = mapper.writeValueAsString(request);
        assertTrue(serialized.contains("\"shop_id\""));
        assertTrue(serialized.contains("\"from_location\""));
    }

    @Test
    void toolResponseAndTraceSerializeSnakeCase() throws Exception {
        AgentToolTraceDTO trace = new AgentToolTraceDTO();
        trace.setToolName("get_coupon_list");
        trace.setBackendSource("java_api");
        trace.setDurationMs(12L);
        trace.setInput(Map.of("shop_id", "shop_001"));
        trace.setStatus("ok");
        trace.setItemCount(1);
        trace.setMissingShopIds(List.of("shop_missing"));
        trace.setWarnings(List.of("warn"));
        trace.setErrorType("NETWORK_ERROR");
        trace.setErrorMessage("boom");

        AgentToolResponse response = AgentToolResponse.ok(Map.of("trace", trace));
        response.setErrorCode("TOOL_TIMEOUT");
        response.setErrorMessage("timeout");

        String json = mapper.writeValueAsString(response);

        assertTrue(json.contains("\"result_status\""));
        assertTrue(json.contains("\"error_code\""));
        assertTrue(json.contains("\"error_message\""));
        assertTrue(json.contains("\"backend_source\""));
        assertTrue(json.contains("\"tool_name\""));
        assertTrue(json.contains("\"missing_shop_ids\""));
    }
}
