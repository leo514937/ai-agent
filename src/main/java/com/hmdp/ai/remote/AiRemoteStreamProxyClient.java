package com.hmdp.ai.remote;

import cn.hutool.core.util.StrUtil;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import javax.annotation.Resource;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

@Slf4j
@Component
public class AiRemoteStreamProxyClient {

    private static final String STREAM_PATH = "/internal/v1/chat/stream";
    private static final int DEFAULT_CONNECT_TIMEOUT_MS = 3000;
    // 流式 SSE 可能在检索/推理阶段停顿较久，读超时需要明显长于普通 JSON 请求。
    private static final int DEFAULT_READ_TIMEOUT_MS = 120000;

    @Resource
    private AiRemoteProperties properties;
    @Resource
    private ObjectMapper objectMapper;

    public void stream(AiRemoteChatRequest request, OutputStream outputStream) throws IOException {
        if (request == null) {
            throw new IOException("远端请求不能为空");
        }
        if (outputStream == null) {
            throw new IOException("输出流不能为空");
        }
        if (properties == null || !properties.isAvailable()) {
            throw new IOException("远端 AI 未启用");
        }

        HttpURLConnection connection = null;
        InputStream responseStream = null;
        try {
            String endpoint = properties.resolveBaseUrl() + STREAM_PATH;
            connection = (HttpURLConnection) new URL(endpoint).openConnection();
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            connection.setConnectTimeout(DEFAULT_CONNECT_TIMEOUT_MS);
            connection.setReadTimeout(DEFAULT_READ_TIMEOUT_MS);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            connection.setRequestProperty("Accept", "text/event-stream");
            if (StrUtil.isNotBlank(properties.getInternalToken())) {
                connection.setRequestProperty("x-internal-token", properties.getInternalToken());
            }

            try (OutputStream remoteOutputStream = connection.getOutputStream()) {
                remoteOutputStream.write(objectMapper.writeValueAsBytes(request.toPayloadMap()));
                remoteOutputStream.flush();
            }

            int status = connection.getResponseCode();
            String contentType = connection.getContentType();
            responseStream = status >= 200 && status < 300 ? connection.getInputStream() : connection.getErrorStream();
            if (responseStream == null) {
                throw new IOException("远端没有返回可读取的响应体");
            }
            if (StrUtil.isBlank(contentType) || !contentType.toLowerCase().contains("text/event-stream")) {
                throw new IOException("远端未返回 SSE 响应(contentType=" + contentType + ", status=" + status + ")");
            }

            byte[] buffer = new byte[1024];
            int read;
            boolean clientDisconnected = false;
            while (true) {
                try {
                    read = responseStream.read(buffer);
                } catch (IOException e) {
                    log.debug("读取远端 AI stream 失败：{}", e.getMessage());
                    throw e;
                }
                if (read < 0) {
                    break;
                }
                if (!clientDisconnected) {
                    try {
                        outputStream.write(buffer, 0, read);
                        outputStream.flush();
                    } catch (IOException e) {
                        // 客户端断开连接了（例如刷新页面或切换UI）！我们捕获它，并在后台把远端 stream 读完以确保后端正常执行完毕。
                        log.debug("客户端已断开连接，后台继续读取远端流数据以确保后端执行完毕：{}", e.getMessage());
                        clientDisconnected = true;
                    }
                }
            }
        } catch (IOException ex) {
            log.debug("远端 stream 代理失败：{}", ex.getMessage());
            throw ex;
        } catch (Exception ex) {
            log.debug("远端 stream 代理异常：{}", ex.getMessage());
            throw new IOException(firstNonBlank(ex.getMessage(), "远端 stream 代理失败"), ex);
        } finally {
            if (responseStream != null) {
                try {
                    responseStream.close();
                } catch (IOException ignore) {
                    // ignore
                }
            }
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private String firstNonBlank(String... values) {
        if (values == null) {
            return null;
        }
        for (String value : values) {
            if (StrUtil.isNotBlank(value)) {
                return value;
            }
        }
        return null;
    }
}
