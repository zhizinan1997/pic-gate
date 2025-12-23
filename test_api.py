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
    ]
}

print("发送请求到:", url)
print("请求体:", json.dumps(data, ensure_ascii=False, indent=2))
print("\n等待响应...\n")

try:
    response = requests.post(url, headers=headers, json=data, timeout=120)
    print("状态码:", response.status_code)
    print("响应头:", dict(response.headers))
    print("\n响应体:")
    try:
        resp_json = response.json()
        print(json.dumps(resp_json, ensure_ascii=False, indent=2))
        
        # 检查是否是空回复
        if "choices" in resp_json:
            for i, choice in enumerate(resp_json["choices"]):
                print(f"\n--- Choice {i} ---")
                message = choice.get("message", {})
                content = message.get("content", "")
                print(f"Content 长度: {len(content) if content else 0}")
                print(f"Content 内容: {repr(content)}")
    except:
        print(response.text)
except Exception as e:
    print(f"请求错误: {e}")
