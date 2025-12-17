
import asyncio
import sys
import httpx
from app.db import async_session_maker
from app.services.settings_service import get_settings

async def debug_check():
    try:
        async with async_session_maker() as session:
            settings = await get_settings(session)
            print("-" * 30)
            print("Testing POST to: /chat/completions with model='gpt-3.5-turbo'")
            
            headers = {
                "Authorization": f"Bearer {settings.upstream_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "gpt-3.5-turbo",  # Change model to test connectivity
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": False
            }
            
            try:
                # Timeout of 10s should be enough for a simple Hi
                async with httpx.AsyncClient(verify=True, timeout=10.0) as client:
                    response = await client.post(
                        f"{settings.upstream_api_base}/chat/completions",
                        json=payload,
                        headers=headers
                    )
                    print(f"Response Status: {response.status_code}")
                    print(f"Response First 100 bytes: {response.text[:100]}")
                    
                    if response.status_code == 200:
                        print("Connectivity: SUCCESS")
                    else:
                        print("Connectivity: SUCCESS (but upstream returned validation error)")
                        
            except httpx.RequestError as e:
                print(f"Connectivity: FAILED (RequestError)")
                print(f"Error class: {type(e)}")
                print(f"Error details: {e}")
            except httpx.HTTPStatusError as e:
                print(f"Connectivity: FAILED (HTTPStatusError)")
                print(f"Error: {e}")

    except Exception as e:
        print(f"Script Error: {e}")

if __name__ == "__main__":
    asyncio.run(debug_check())
