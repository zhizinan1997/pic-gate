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
    "stream": True  # 测试交互式流式响应
}

print("=" * 70)
print("测试交互式流式响应 - nano banana🍌 模型")
print("=" * 70)
print()
print("预期流程:")
print("1. 收到欢迎消息")
print("2. 每3秒收到计时更新")
print("3. 收到图片处理消息")
print("4. 收到最终图片URL")
print()
print("-" * 70)

try:
    start = time.time()
    response = requests.post(url, headers=headers, json=data, timeout=300, stream=True)
    print(f"状态码: {response.status_code}")
    print()
    
    full_content = ""
    chunk_count = 0
    
    for line in response.iter_lines():
        if line:
            line_str = line.decode('utf-8')
            chunk_count += 1
            
            if line_str.startswith("data: "):
                data_str = line_str[6:]
                if data_str == "[DONE]":
                    elapsed = time.time() - start
                    print(f"\n[流结束] 总耗时: {elapsed:.2f}秒")
                    break
                try:
                    chunk_data = json.loads(data_str)
                    if "choices" in chunk_data and len(chunk_data["choices"]) > 0:
                        delta = chunk_data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            full_content += content
                            # 实时显示内容
                            print(content, end="", flush=True)
                except json.JSONDecodeError:
                    pass
    
    print()
    print("-" * 70)
    print(f"总共收到 {chunk_count} 个chunk")
    print(f"完整内容长度: {len(full_content)} 字符")
    
except Exception as e:
    print(f"请求错误: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
print("测试完成")
