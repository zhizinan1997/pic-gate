import requests
import json
import time

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
    "stream": True  # 测试流式响应
}

print("=" * 60)
print("测试流式响应")
print("=" * 60)
print()

try:
    start = time.time()
    response = requests.post(url, headers=headers, json=data, timeout=180, stream=True)
    print(f"状态码: {response.status_code}")
    print(f"响应头 Content-Type: {response.headers.get('Content-Type', 'N/A')}")
    print()
    print("流式响应内容:")
    print("-" * 40)
    
    full_content = ""
    chunk_count = 0
    
    for line in response.iter_lines():
        if line:
            line_str = line.decode('utf-8')
            chunk_count += 1
            print(f"[Chunk {chunk_count}] {line_str[:100]}{'...' if len(line_str) > 100 else ''}")
            
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
                except json.JSONDecodeError:
                    pass
    
    elapsed = time.time() - start
    print("-" * 40)
    print(f"\n总共收到 {chunk_count} 个chunk, 耗时: {elapsed:.2f}s")
    print(f"\n完整内容长度: {len(full_content)}")
    if full_content:
        print(f"完整内容: {full_content[:500]}{'...' if len(full_content) > 500 else ''}")
    
except Exception as e:
    print(f"请求错误: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("测试完成")
