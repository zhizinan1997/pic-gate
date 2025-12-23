import requests
import json

# 直接测试上游 Gemini API
url = "https://gemini.zhizinan.top/antigravity/v1/chat/completions"
headers = {
    "Content-Type": "application/json",
    # 你可能需要提供上游的实际API密钥
}
data = {
    "model": "gemini-3-pro-image",  # 从之前响应看到的模型名
    "messages": [
        {
            "role": "user",
            "content": "请说一个简单的词"
        }
    ],
    "stream": False
}

print("直接测试上游 Gemini API")
print("URL:", url)
print()

for i in range(3):
    print(f"--- 请求 {i+1}/3 ---")
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        print(f"状态码: {response.status_code}")
        if response.status_code == 200:
            print("成功!")
        else:
            print(f"错误: {response.text[:200]}")
    except Exception as e:
        print(f"异常: {e}")
    print()
