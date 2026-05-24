import sys
import httpx
import json
import uuid

def test_chat_stream():
    url = "http://127.0.0.1:8000/internal/v1/chat/stream"
    headers = {
        "x-internal-token": "local-learning-agent-token", # 内部通讯Token
        "Content-Type": "application/json"
    }
    
    payload = {
        "user_id": "test_user_123",
        "session_id": str(uuid.uuid4()),
        "trace_id": str(uuid.uuid4()),
        "message": "帮我查一下附近有没有什么好的川菜馆？",
        "turn_id": str(uuid.uuid4())
    }
    
    print(f"Sending stream request to {url}...")
    print(f"Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    print("-" * 50)
    
    accumulated_answer = []
    
    try:
        with httpx.stream("POST", url, headers=headers, json=payload, timeout=60.0) as response:
            if response.status_code != 200:
                print(f"Error status code: {response.status_code}")
                print(response.read().decode('utf-8'))
                return
                
            for line in response.iter_lines():
                if not line.strip():
                    continue
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        print("\n[Stream DONE]")
                        break
                    try:
                        event = json.loads(data_str)
                        event_type = event.get("event_type")
                        payload_data = event.get("payload", {})
                        
                        if event_type == "answer_delta":
                            delta = payload_data.get("delta", "")
                            accumulated_answer.append(delta)
                            # 实时打印 delta
                            sys.stdout.write(delta)
                            sys.stdout.flush()
                        else:
                            # 其它事件打印简短状态，不污染控制台的流式打印
                            print(f"\n[Event: {event_type}]")
                    except Exception as e:
                        print(f"\n[Error parsing event]: {e} on raw data: {data_str}")
    except Exception as e:
        print(f"\n[Request failed]: {e}")
        
    print("\n" + "-" * 50)
    final_text = "".join(accumulated_answer)
    print("Accumulated final response:")
    print(final_text)
    
    # 验证 details 标签的匹配性
    details_open_count = final_text.count("<details open>")
    details_close_count = final_text.count("</details>")
    print(f"Details open tag count: {details_open_count}")
    print(f"Details close tag count: {details_close_count}")
    
    if details_open_count == details_close_count:
        print("✅ SUCCESS: HTML Details tags are perfectly balanced!")
    else:
        print("❌ ERROR: HTML Details tags are imbalanced!")

if __name__ == "__main__":
    test_chat_stream()
