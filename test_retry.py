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
    "stream": False
}

print("=" * 60)
print("测试重试机制 - 连续发送3次请求")
print("=" * 60)

for i in range(3):
    print(f"\n--- 请求 {i+1}/3 ---")
    try:
        start = time.time()
        response = requests.post(url, headers=headers, json=data, timeout=180)
        elapsed = time.time() - start
        
        print(f"状态码: {response.status_code}, 耗时: {elapsed:.2f}s")
        
        if response.status_code == 200:
            resp_json = response.json()
            if "choices" in resp_json and len(resp_json["choices"]) > 0:
                content = resp_json["choices"][0].get("message", {}).get("content", "")
                print(f"Content 长度: {len(content) if content else 0}")
                
                # 检查是否是错误消息
                if content and "上游API请求失败" in content:
                    print("⚠️ 收到错误消息 (重试机制生效):")
                    print(content[:500])
                elif content:
                    print(f"Content: {content[:200]}{'...' if len(content) > 200 else ''}")
                else:
                    print("⚠️ Content 为空!")
            else:
                print("响应:", json.dumps(resp_json, ensure_ascii=False)[:300])
        else:
            print("错误响应:", response.text[:500])
            
    except Exception as e:
        print(f"请求错误: {e}")
    
    time.sleep(3)

print("\n" + "=" * 60)
print("测试完成")
