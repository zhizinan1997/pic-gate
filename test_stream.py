import requests
import json

url = "https://gate.zhizinan.top/v1/chat/completions"
headers = {
    "Content-Type": "application/json",
    "Authorization": "Bearer zzn1997912"
}
data = {
    "model": "gemini-draw-gate",
    "messages": [
        {
            "role": "user",
            "content": "请画一只可爱的小猫"
        }
    ],
    "stream": True  # 启用流式模式
}

print("发送流式请求到:", url)
print("请求体:", json.dumps(data, ensure_ascii=False, indent=2))
print("\n等待响应...\n")
print("=" * 50)

try:
    response = requests.post(url, headers=headers, json=data, timeout=120, stream=True)
    print("状态码:", response.status_code)
    print("响应头:", dict(response.headers))
    print("\n流式响应内容:")
    print("-" * 50)
    
    full_content = ""
    chunk_count = 0
    
    for line in response.iter_lines():
        if line:
            line_str = line.decode('utf-8')
            print(f"Chunk {chunk_count}: {repr(line_str)}")
            chunk_count += 1
            
            if line_str.startswith("data: "):
                data_str = line_str[6:]
                if data_str == "[DONE]":
                    print("\n[流结束]")
                    break
                try:
                    chunk_data = json.loads(data_str)
                    if "choices" in chunk_data and len(chunk_data["choices"]) > 0:
                        delta = chunk_data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            full_content += content
                            print(f"  -> content: {repr(content)}")
                except json.JSONDecodeError as e:
                    print(f"  -> JSON解析错误: {e}")
    
    print("-" * 50)
    print(f"\n总共收到 {chunk_count} 个chunk")
    print(f"\n完整内容长度: {len(full_content)}")
    print(f"完整内容: {repr(full_content)}")
    
except Exception as e:
    print(f"请求错误: {e}")
    import traceback
    traceback.print_exc()
