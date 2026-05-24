import os
import sys
import time
from dotenv import load_dotenv

# 加载 .env 配置文件
dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path)

from openai import OpenAI
import httpx

class OpenRouterFilterTransport(httpx.HTTPTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = super().handle_request(request)
        content_type = response.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            # We wrap the response stream to filter out "response.keep_alive" events
            original_stream = response.stream
            
            def filtered_stream():
                buffer = b""
                for chunk in original_stream:
                    buffer += chunk
                    # SSE events are separated by double newlines: \n\n or \r\n\r\n
                    while b"\n\n" in buffer or b"\r\n\r\n" in buffer:
                        # Find the boundary
                        boundary = b"\r\n\r\n" if b"\r\n\r\n" in buffer else b"\n\n"
                        parts = buffer.split(boundary, 1)
                        event_block = parts[0]
                        buffer = parts[1]
                        
                        # Check if this event block contains "response.keep_alive"
                        if b"response.keep_alive" in event_block:
                            # Skip this event block
                            continue
                        
                        # Yield the original block with boundary
                        yield event_block + boundary
                if buffer:
                    if b"response.keep_alive" not in buffer:
                        yield buffer
                        
            class FilteredByteStream(httpx.SyncByteStream):
                def __iter__(self):
                    return filtered_stream()
                def close(self):
                    original_stream.close()

            response.stream = FilteredByteStream()
        return response

api_key = os.environ.get("OPENAI_API_KEY")
base_url = os.environ.get("OPENAI_BASE_URL")
model = os.environ.get("LEARNING_AGENT_OPENAI_RESPONSES_MODEL", "deepseek/deepseek-v4-flash")

print(f"Testing OpenAI client with API_KEY: ...{api_key[-10:] if api_key else 'None'}")
print(f"BASE_URL: {base_url}")
print(f"Model: {model}")

# Create the client with our custom filter transport
client = OpenAI(
    api_key=api_key,
    base_url=base_url,
    http_client=httpx.Client(transport=OpenRouterFilterTransport()),
)

print("\n--- Test responses.stream ---")
try:
    start_time = time.time()
    responses = getattr(client, "responses", None)
    if responses is None:
        print("client has no 'responses' attribute!")
        sys.exit(1)
        
    with responses.stream(
        model=model,
        input=[
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "写一首短诗，关于微风。"}],
            }
        ],
        max_output_tokens=300,
    ) as stream:
        print("Stream started...")
        for event in stream:
            elapsed = time.time() - start_time
            event_type = getattr(event, 'type', None)
            delta = getattr(event, 'delta', None)
            print(f"[{elapsed:.2f}s] Event type: {event_type}")
            if delta is not None:
                print(f"  Delta: {repr(delta)}")
            # Print entire event representation if it has other content fields
            if hasattr(event, 'reasoning_text'):
                print(f"  Reasoning Text: {repr(event.reasoning_text)}")
            if hasattr(event, 'output_text'):
                print(f"  Output Text: {repr(event.output_text)}")
            if event_type == "response.output_text.delta":
                print(f"  OUTPUT DELTA: {repr(event.delta)}")
            elif event_type == "response.reasoning_text.delta":
                print(f"  REASONING DELTA: {repr(event.delta)}")
except Exception as e:
    print(f"Error during responses.stream: {e}")
