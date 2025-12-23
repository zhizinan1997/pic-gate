"""
PicGate OpenAI-Compatible Gateway API
Exposes /v1/* endpoints for OpenWebUI integration.

Phase C Implementation:
- /v1/images/generations - Text to image
- /v1/images/edits - Image editing (img2img) with URL→base64 conversion
- /v1/chat/completions - Multi-turn chat with image URL→base64 conversion
"""

import time
import logging
from typing import Optional, Any, Dict, List
from fastapi import APIRouter, Request, Depends, HTTPException, Header
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
import httpx

from app.db import get_db
from app.services.settings_service import get_settings
from app.services.upstream_client import UpstreamClient
from app.services.image_store import ImageStore, is_base64_image
from app.services.url_builder import get_public_base_url, build_image_url
from app.services.payload_rewriter import PayloadRewriter, create_rewriter
from app.routers.admin_api import add_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["OpenAI Gateway"])


# --- Request/Response Models ---

class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "picgate"


class ModelsResponse(BaseModel):
    object: str = "list"
    data: list[ModelInfo]


class ErrorDetail(BaseModel):
    message: str
    type: str = "invalid_request_error"
    code: Optional[str] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ImageGenerationRequest(BaseModel):
    prompt: str
    model: Optional[str] = None
    n: Optional[int] = 1
    size: Optional[str] = "1024x1024"
    quality: Optional[str] = "standard"
    style: Optional[str] = "vivid"
    response_format: Optional[str] = "url"  # We always return URL, ignore b64_json
    

# --- Authentication Dependency ---

async def verify_gateway_auth(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
) -> bool:
    """
    Verify the gateway API key from Authorization header.
    Expected format: Bearer {gateway_api_key}
    """
    settings = await get_settings(db)
    
    if not settings.gateway_api_key:
        # No API key configured - allow access (for initial setup)
        logger.warning("Gateway API key not configured - requests are unauthenticated!")
        return True
    
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail={"error": {"message": "Missing Authorization header", "type": "auth_error"}}
        )
    
    # Parse Bearer token
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail={"error": {"message": "Invalid Authorization header format. Expected: Bearer <token>", "type": "auth_error"}}
        )
    
    token = parts[1]
    if token != settings.gateway_api_key:
        raise HTTPException(
            status_code=401,
            detail={"error": {"message": "Invalid API key", "type": "auth_error"}}
        )
    
    return True


def create_error_response(message: str, error_type: str = "api_error", status_code: int = 500) -> JSONResponse:
    """Create a standardized OpenAI-style error response."""
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message, "type": error_type}}
    )


# --- Endpoints ---

@router.get("/models", response_model=ModelsResponse)
async def list_models(
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_gateway_auth)
):
    """
    List available models.
    Returns the gateway model name configured in settings.
    """
    settings = await get_settings(db)
    
    model_name = settings.gateway_model_name or "picgate"
    
    return ModelsResponse(
        data=[
            ModelInfo(
                id=model_name,
                created=int(time.time())
            )
        ]
    )


@router.post("/images/generations")
async def create_image(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_gateway_auth)
):
    """
    Generate images from text prompt.
    
    Flow:
    1. Receive request from OpenWebUI
    2. Forward to upstream with b64_json format
    3. Save base64 images to local storage
    4. Return URLs pointing to our /images/{id} endpoint
    """
    settings = await get_settings(db)
    
    # Validate upstream configuration
    if not settings.upstream_api_base or not settings.upstream_api_key:
        return create_error_response(
            "Upstream API not configured. Please configure in admin settings.",
            "configuration_error",
            503
        )
    
    # Parse request body
    try:
        body = await request.json()
    except Exception as e:
        return create_error_response(f"Invalid JSON body: {e}", "invalid_request", 400)
    
    prompt = body.get("prompt")
    if not prompt:
        return create_error_response("Missing required field: prompt", "invalid_request", 400)
    
    # Get parameters with defaults
    n = body.get("n", 1)
    size = body.get("size", "1024x1024")
    quality = body.get("quality", "standard")
    style = body.get("style", "vivid")
    
    # Create upstream client
    client = UpstreamClient(
        api_base=settings.upstream_api_base,
        api_key=settings.upstream_api_key
    )
    
    add_log("INFO", f"📤 发起文生图请求: prompt={prompt[:50]}...")
    
    try:
        # Call upstream API (always requests b64_json)
        upstream_response = await client.generate_image(
            prompt=prompt,
            model=settings.upstream_model_name or "dall-e-3",
            n=n,
            size=size,
            quality=quality,
            style=style
        )
        add_log("INFO", f"📥 上游返回成功: 收到 {len(upstream_response.get('data', []))} 张图片")
    except httpx.HTTPStatusError as e:
        logger.error(f"Upstream API error: {e}")
        add_log("ERROR", f"❌ 上游返回错误: HTTP {e.response.status_code}")
        return create_error_response(
            f"Upstream API returned error: {e.response.status_code}",
            "upstream_error",
            502
        )
    except httpx.RequestError as e:
        logger.error(f"Upstream connection error: {e}")
        add_log("ERROR", f"❌ 上游连接失败: {str(e)[:50]}")
        return create_error_response(
            "Failed to connect to upstream API",
            "connection_error",
            502
        )
    except Exception as e:
        logger.error(f"Unexpected error calling upstream: {e}")
        add_log("ERROR", f"❌ 请求异常: {str(e)[:50]}")
        return create_error_response(
            "Internal error processing request",
            "internal_error",
            500
        )
    
    # Process response - save images and build URLs
    image_store = ImageStore(db)
    result_data = []
    
    for item in upstream_response.get("data", []):
        b64_data = item.get("b64_json")
        if not b64_data:
            logger.warning("Upstream response missing b64_json data")
            continue
        
        try:
            # Save to local storage
            image = await image_store.save_from_base64(b64_data)
            
            # Build public URL
            image_url = await build_image_url(request, db, image.image_id)
            
            result_data.append({
                "url": image_url,
                "revised_prompt": item.get("revised_prompt")  # Pass through if present
            })
            
            logger.info(f"Generated image {image.image_id}, URL: {image_url}")
            add_log("INFO", f"文生图完成: {image.image_id[:8]}...")
            
        except Exception as e:
            logger.error(f"Failed to save image: {e}")
            continue
    
    if not result_data:
        return create_error_response(
            "No images were generated successfully",
            "generation_error",
            500
        )
    
    # Return OpenAI-compatible response
    return {
        "created": int(time.time()),
        "data": result_data
    }


@router.post("/images/edits")
async def edit_image(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_gateway_auth)
):
    """
    Edit/modify existing images (img2img).
    
    Flow:
    1. Receive request with image (and optional mask) - can be URL or base64
    2. Use PayloadRewriter to convert any URLs to base64
    3. Forward to upstream API
    4. Save returned images and return URLs
    
    Supports:
    - image: Base64 or URL of the image to edit
    - mask: Optional base64 or URL of the mask
    - prompt: Edit instructions
    - n, size: Standard generation parameters
    """
    settings = await get_settings(db)
    
    # Validate upstream configuration
    if not settings.upstream_api_base or not settings.upstream_api_key:
        return create_error_response(
            "Upstream API not configured. Please configure in admin settings.",
            "configuration_error",
            503
        )
    
    # Parse request body
    try:
        body = await request.json()
    except Exception as e:
        return create_error_response(f"Invalid JSON body: {e}", "invalid_request", 400)
    
    # Validate required fields
    if not body.get("image"):
        return create_error_response("Missing required field: image", "invalid_request", 400)
    if not body.get("prompt"):
        return create_error_response("Missing required field: prompt", "invalid_request", 400)
    
    # Create payload rewriter to convert URLs to base64
    rewriter = await create_rewriter(db, settings)
    
    try:
        # Rewrite the entire body - converts image/mask URLs to base64
        rewritten_body = await rewriter.rewrite(body)
    except ValueError as e:
        # External image fetch not allowed
        return create_error_response(str(e), "security_error", 400)
    except Exception as e:
        logger.error(f"Payload rewriting failed: {e}")
        return create_error_response(
            f"Failed to process image URLs: {e}",
            "processing_error",
            400
        )
    
    # Extract parameters
    image_base64 = rewritten_body.get("image")
    mask_base64 = rewritten_body.get("mask")
    prompt = rewritten_body.get("prompt")
    n = rewritten_body.get("n", 1)
    size = rewritten_body.get("size", "1024x1024")
    
    # Strip data URL prefix if present (upstream expects raw base64)
    if image_base64 and image_base64.startswith("data:"):
        image_base64 = image_base64.split(",", 1)[1] if "," in image_base64 else image_base64
    if mask_base64 and mask_base64.startswith("data:"):
        mask_base64 = mask_base64.split(",", 1)[1] if "," in mask_base64 else mask_base64
    
    # Create upstream client
    client = UpstreamClient(
        api_base=settings.upstream_api_base,
        api_key=settings.upstream_api_key
    )
    
    try:
        # Call upstream API for image editing
        upstream_response = await client.edit_image(
            image_base64=image_base64,
            prompt=prompt,
            model=settings.upstream_model_name or "dall-e-2",
            mask_base64=mask_base64,
            n=n,
            size=size
        )
    except httpx.HTTPStatusError as e:
        logger.error(f"Upstream API error: {e}")
        # Try to extract error message from response
        try:
            error_detail = e.response.json().get("error", {}).get("message", str(e))
        except Exception:
            error_detail = str(e.response.status_code)
        return create_error_response(
            f"Upstream API error: {error_detail}",
            "upstream_error",
            502
        )
    except httpx.RequestError as e:
        logger.error(f"Upstream connection error: {e}")
        return create_error_response(
            "Failed to connect to upstream API",
            "connection_error",
            502
        )
    except Exception as e:
        logger.error(f"Unexpected error calling upstream: {e}")
        return create_error_response(
            "Internal error processing request",
            "internal_error",
            500
        )
    
    # Process response - save images and build URLs
    image_store = ImageStore(db)
    result_data = []
    
    for item in upstream_response.get("data", []):
        b64_data = item.get("b64_json")
        if not b64_data:
            logger.warning("Upstream response missing b64_json data")
            continue
        
        try:
            # Save to local storage
            image = await image_store.save_from_base64(b64_data)
            
            # Build public URL
            image_url = await build_image_url(request, db, image.image_id)
            
            result_data.append({
                "url": image_url,
                "revised_prompt": item.get("revised_prompt")
            })
            
            logger.info(f"Edited image saved as {image.image_id}, URL: {image_url}")
            
        except Exception as e:
            logger.error(f"Failed to save edited image: {e}")
            continue
    
    if not result_data:
        return create_error_response(
            "No images were generated successfully",
            "generation_error",
            500
        )
    
    # Return OpenAI-compatible response
    return {
        "created": int(time.time()),
        "data": result_data
    }


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_gateway_auth)
):
    """
    Chat completions with image support (streaming and non-streaming).
    
    CRITICAL: This endpoint handles multi-turn conversations where images
    may be referenced by URL in the messages. Before forwarding to upstream,
    all image URLs must be converted to base64.
    
    Flow:
    1. Receive chat completion request with messages
    2. Use PayloadRewriter to convert ALL image URLs to base64
    3. Forward to upstream API (streaming or non-streaming based on request)
    4. Process response:
       - If response contains images (base64), save them and return URLs
       - If response is text, pass through as-is
    """
    settings = await get_settings(db)
    
    # Validate upstream configuration
    if not settings.upstream_api_base or not settings.upstream_api_key:
        return create_error_response(
            "Upstream API not configured. Please configure in admin settings.",
            "configuration_error",
            503
        )
    
    # Parse request body
    try:
        body = await request.json()
    except Exception as e:
        return create_error_response(f"Invalid JSON body: {e}", "invalid_request", 400)
    
    # Validate required fields
    if not body.get("messages"):
        return create_error_response("Missing required field: messages", "invalid_request", 400)
    
    # Check if streaming is requested
    is_streaming = body.get("stream", False)
    
    # Create payload rewriter to convert URLs to base64
    rewriter = await create_rewriter(db, settings)
    
    try:
        # Rewrite the entire body - deep traversal converts all image URLs to base64
        # This handles:
        # - messages[].content[].image_url.url
        # - messages[].content[].input_image.url
        # - tool_calls/function_call arguments
        # - Any nested image/init_image/mask fields
        rewritten_body = await rewriter.rewrite(body)
    except ValueError as e:
        # External image fetch not allowed
        return create_error_response(str(e), "security_error", 400)
    except Exception as e:
        logger.error(f"Payload rewriting failed: {e}")
        return create_error_response(
            f"Failed to process image URLs in messages: {e}",
            "processing_error",
            400
        )
    
    # Map model name: replace gateway model with upstream model
    if rewritten_body.get("model") == settings.gateway_model_name:
        rewritten_body["model"] = settings.upstream_model_name or rewritten_body.get("model")
    
    # Create upstream client
    client = UpstreamClient(
        api_base=settings.upstream_api_base,
        api_key=settings.upstream_api_key
    )
    
    msg_count = len(rewritten_body.get("messages", []))
    
    # Handle streaming mode
    if is_streaming:
        add_log("INFO", f"📤 发起流式对话请求: {msg_count} 条消息")
        return await _handle_streaming_chat(client, rewritten_body, settings, request, db)
    
    # Non-streaming mode
    rewritten_body["stream"] = False
    add_log("INFO", f"📤 发起对话请求: {msg_count} 条消息")
    
    # Retry mechanism: try up to 3 times
    max_retries = 3
    last_error = None
    last_error_detail = None
    last_error_response = None
    
    for attempt in range(1, max_retries + 1):
        try:
            # Call upstream API for chat completions
            upstream_response = await client.chat_completions(
                messages=rewritten_body.get("messages", []),
                model=rewritten_body.get("model", settings.upstream_model_name or "gpt-4-vision-preview"),
                **{k: v for k, v in rewritten_body.items() if k not in ("messages", "model", "stream")}
            )
            add_log("INFO", f"📥 上游对话返回成功" + (f" (第{attempt}次尝试)" if attempt > 1 else ""))
            break  # Success, exit retry loop
            
        except httpx.HTTPStatusError as e:
            last_error = e
            # Try to extract error message and full response
            try:
                last_error_response = e.response.text
                error_json = e.response.json()
                last_error_detail = error_json.get("error", {}).get("message", str(e))
            except Exception:
                last_error_detail = str(e.response.status_code)
                last_error_response = e.response.text if hasattr(e.response, 'text') else str(e)
            
            logger.warning(f"Upstream API error (attempt {attempt}/{max_retries}): {last_error_detail[:100]}")
            add_log("WARNING", f"⚠️ 上游错误 (尝试 {attempt}/{max_retries}): {last_error_detail[:50]}")
            
            if attempt < max_retries:
                import asyncio
                await asyncio.sleep(1)  # Wait 1 second before retry
                continue
                
        except httpx.RequestError as e:
            last_error = e
            last_error_detail = f"Connection error: {str(e)}"
            last_error_response = str(e)
            
            logger.warning(f"Upstream connection error (attempt {attempt}/{max_retries}): {e}")
            add_log("WARNING", f"⚠️ 连接错误 (尝试 {attempt}/{max_retries}): {str(e)[:50]}")
            
            if attempt < max_retries:
                import asyncio
                await asyncio.sleep(1)
                continue
                
        except Exception as e:
            last_error = e
            last_error_detail = f"Unexpected error: {str(e)}"
            last_error_response = str(e)
            
            logger.warning(f"Unexpected error (attempt {attempt}/{max_retries}): {e}")
            add_log("WARNING", f"⚠️ 异常 (尝试 {attempt}/{max_retries}): {str(e)[:50]}")
            
            if attempt < max_retries:
                import asyncio
                await asyncio.sleep(1)
                continue
    else:
        # All retries failed - return error info as content for debugging
        logger.error(f"All {max_retries} attempts failed. Last error: {last_error_detail}")
        add_log("ERROR", f"❌ 所有 {max_retries} 次重试均失败")
        
        # Build error message as chat content for client debugging
        error_content = f"""⚠️ **上游API请求失败 (已重试{max_retries}次)**

**错误信息:** {last_error_detail}

**完整响应:**
```
{last_error_response[:2000] if last_error_response else 'N/A'}
```

请检查上游API服务是否正常运行。"""
        
        # Return as a valid chat completion response with error as content
        return {
            "id": f"chatcmpl-error-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": rewritten_body.get("model", "unknown"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": error_content
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        }
    
    # Process response - check if any images need to be saved
    # Some models return images in the response as base64
    image_store = ImageStore(db)
    
    try:
        processed_response = await _process_chat_response(
            upstream_response, 
            image_store, 
            request, 
            db
        )
        return processed_response
    except Exception as e:
        logger.error(f"Error processing chat response: {e}")
        # Return original response if processing fails
        return upstream_response


async def _handle_streaming_chat(
    client: UpstreamClient,
    rewritten_body: Dict[str, Any],
    settings,
    request: Request,
    db: AsyncSession
) -> StreamingResponse:
    """
    Handle streaming chat completions with interactive progress updates.
    
    For image generation requests, provides:
    1. Welcome message immediately
    2. Timer updates every 3 seconds
    3. Processing notification when image is received
    4. Final image URL delivery
    
    For regular chat, streams response directly.
    """
    import asyncio
    import json as json_module
    
    model_name = rewritten_body.get("model", "unknown")
    chat_id = f"chatcmpl-{int(time.time() * 1000)}"
    
    def make_chunk(content: str, finish_reason=None, include_role=False):
        """Helper to create a valid SSE chunk."""
        delta = {"content": content}
        if include_role:
            delta["role"] = "assistant"
        
        chunk = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "delta": delta if not finish_reason else {},
                    "finish_reason": finish_reason
                }
            ]
        }
        return f"data: {json_module.dumps(chunk, ensure_ascii=False)}\n\n"
    
    # Check if this is likely an image generation/editing request
    # Simplified: Any URL or structured image content triggers interactive mode
    messages = rewritten_body.get("messages", [])
    last_message = messages[-1] if messages else {}
    
    # Get content - could be string or array
    last_content_raw = last_message.get("content", "")
    
    # Convert to string for analysis
    if isinstance(last_content_raw, str):
        last_content = last_content_raw
    elif isinstance(last_content_raw, list):
        text_parts = []
        for item in last_content_raw:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
        last_content = " ".join(text_parts)
    else:
        last_content = ""
    
    # Extract image URLs from the message for display
    import re
    uploaded_image_urls = []
    
    # Check for URLs in string content
    if isinstance(last_content_raw, str):
        # Match any http/https URL
        url_pattern = r'https?://[^\s\)\]\"\'<>]+'
        uploaded_image_urls = re.findall(url_pattern, last_content_raw)
    
    # Check for structured content with image_url
    has_structured_image = False
    if isinstance(last_content_raw, list):
        for item in last_content_raw:
            if isinstance(item, dict):
                if item.get("type") in ("image_url", "image", "input_image"):
                    has_structured_image = True
                    # Try to extract the URL
                    img_url_obj = item.get("image_url") or item.get("input_image") or item.get("image")
                    if isinstance(img_url_obj, dict):
                        url = img_url_obj.get("url", "")
                    elif isinstance(img_url_obj, str):
                        url = img_url_obj
                    else:
                        url = ""
                    if url and not url.startswith("data:"):  # Skip base64
                        uploaded_image_urls.append(url)
    
    # Keywords that suggest image generation/editing
    image_keywords = [
        # 中文关键词
        "画", "绘", "生成图", "图片", "创作", "设计", "制作",
        "换成", "替换", "修改", "编辑", "改成", "变成", "调整", "优化",
        "添加", "删除", "去掉", "加上", "移除", "抠图", "合成",
        "风格", "滤镜", "特效", "背景", "前景", "颜色", "色调",
        # 英文关键词
        "draw", "paint", "generate", "image", "picture", "create", "design",
        "edit", "change", "modify", "replace", "swap", "remove", "add",
        "style", "filter", "effect", "background", "foreground"
    ]
    has_image_keywords = any(kw in last_content.lower() for kw in image_keywords)
    
    # Simplified trigger: ANY URL or structured image content triggers interactive mode
    has_any_url = len(uploaded_image_urls) > 0
    
    is_image_request = has_image_keywords or has_any_url or has_structured_image
    
    logger.info(f"Image request detection: keywords={has_image_keywords}, urls={len(uploaded_image_urls)}, structured={has_structured_image} -> is_image={is_image_request}")
    
    async def generate_interactive_stream():
        """Generate stream with interactive progress updates for image requests."""
        
        # Build elegant welcome message
        if uploaded_image_urls:
            # With uploaded images
            images_md = "\n".join([f"![📷 原图{i}]({url})" for i, url in enumerate(uploaded_image_urls[:3], 1)])
            welcome_msg = f"""## 🎨 PicGate 图像处理中心

---

**📥 已接收您的创作请求**

{images_md}

---

⏳ 正在连接 AI 绘图引擎，请稍候...

"""
        else:
            # Text-only generation request
            welcome_msg = """## 🎨 PicGate 图像处理中心

---

**📥 已接收您的创作请求**

⏳ 正在连接 AI 绘图引擎，请稍候...

"""
        
        yield make_chunk(welcome_msg, include_role=True)
        
        # Start the upstream request in background
        max_retries = 3
        upstream_response = None
        last_error_detail = None
        last_error_response = None
        last_status_code = None
        
        async def fetch_upstream():
            nonlocal upstream_response, last_error_detail, last_error_response, last_status_code
            for attempt in range(1, max_retries + 1):
                try:
                    # Use non-streaming for image generation
                    rewritten_body["stream"] = False
                    upstream_response = await client.chat_completions(
                        messages=rewritten_body.get("messages", []),
                        model=rewritten_body.get("model", settings.upstream_model_name or "gpt-4-vision-preview"),
                        **{k: v for k, v in rewritten_body.items() if k not in ("messages", "model", "stream")}
                    )
                    add_log("INFO", f"📥 上游返回成功" + (f" (第{attempt}次尝试)" if attempt > 1 else ""))
                    return True
                except httpx.HTTPStatusError as e:
                    last_status_code = e.response.status_code
                    try:
                        last_error_response = e.response.text
                        error_json = e.response.json() if hasattr(e.response, 'json') else {}
                        last_error_detail = error_json.get("error", {}).get("message", str(e))
                    except:
                        last_error_detail = str(e.response.status_code)
                    
                    logger.warning(f"Upstream error (attempt {attempt}/{max_retries}): {last_error_detail[:100]}")
                    add_log("WARNING", f"⚠️ 上游错误 (尝试 {attempt}/{max_retries}): {last_error_detail[:50]}")
                    
                    if attempt < max_retries:
                        await asyncio.sleep(1)
                except httpx.RequestError as e:
                    last_error_detail = f"Connection error: {str(e)}"
                    logger.warning(f"Connection error (attempt {attempt}/{max_retries}): {e}")
                    add_log("WARNING", f"⚠️ 连接错误 (尝试 {attempt}/{max_retries}): {str(e)[:50]}")
                    
                    if attempt < max_retries:
                        await asyncio.sleep(1)
                except Exception as e:
                    last_error_detail = f"Unexpected error: {str(e)}"
                    logger.warning(f"Unexpected error (attempt {attempt}/{max_retries}): {e}")
                    add_log("WARNING", f"⚠️ 异常 (尝试 {attempt}/{max_retries}): {str(e)[:50]}")
                    
                    if attempt < max_retries:
                        await asyncio.sleep(1)
            
            return False
        
        # Create the upstream fetch task
        fetch_task = asyncio.create_task(fetch_upstream())
        
        # Send timer updates while waiting
        elapsed_seconds = 0
        while not fetch_task.done():
            await asyncio.sleep(3)
            elapsed_seconds += 3
            
            if not fetch_task.done():
                # Elegant progress indicator
                dots = "•" * ((elapsed_seconds // 3) % 4 + 1)
                timer_msg = f"🔄 **处理中** {dots} 已用时 {elapsed_seconds}s\n"
                yield make_chunk(timer_msg)
        
        # Get the result
        success = await fetch_task
        
        if not success:
            # All retries failed
            add_log("ERROR", f"❌ 所有 {max_retries} 次重试均失败")
            error_msg = f"""\n\n⚠️ **上游API请求失败 (已重试{max_retries}次)**

**HTTP状态码:** {last_status_code or 'N/A'}

**错误信息:** {last_error_detail}

**完整响应:**
```
{(last_error_response or 'N/A')[:2000]}
```

请检查上游API服务是否正常运行。"""
            yield make_chunk(error_msg)
            yield make_chunk("", finish_reason="stop")
            yield "data: [DONE]\n\n"
            return
        
        # Success! Send elegant processing message
        process_msg = "\n\n---\n\n✨ **图像生成成功！** 正在优化输出格式...\n\n"
        yield make_chunk(process_msg)
        
        # Process the response to extract/convert images
        image_store = ImageStore(db)
        
        try:
            processed_response = await _process_chat_response(
                upstream_response, 
                image_store, 
                request, 
                db
            )
            
            # Extract the content from processed response
            if processed_response.get("choices"):
                content = processed_response["choices"][0].get("message", {}).get("content", "")
                if content:
                    # Send elegant final content
                    final_msg = f"""---

## 🖼️ 创作完成

{content}

---

💡 *图片已保存，点击可查看大图*"""
                    yield make_chunk(final_msg)
                else:
                    yield make_chunk("⚠️ 未能获取到图片内容")
            else:
                yield make_chunk("⚠️ 响应格式异常")
                
        except Exception as e:
            logger.error(f"Error processing response: {e}")
            # Fallback: try to extract content directly
            if upstream_response and upstream_response.get("choices"):
                content = upstream_response["choices"][0].get("message", {}).get("content", "")
                yield make_chunk(f"✅ 绘制完成！\n\n{content}" if content else "⚠️ 处理响应时出错")
            else:
                yield make_chunk(f"⚠️ 处理响应时出错: {str(e)}")
        
        # Send finish
        yield make_chunk("", finish_reason="stop")
        yield "data: [DONE]\n\n"
    
    async def generate_passthrough_stream():
        """For non-image requests, pass through upstream stream directly."""
        rewritten_body["stream"] = True
        max_retries = 3
        last_error_detail = None
        last_error_response = None
        last_status_code = None
        
        for attempt in range(1, max_retries + 1):
            try:
                async for line in client.chat_completions_stream(
                    messages=rewritten_body.get("messages", []),
                    model=rewritten_body.get("model", settings.upstream_model_name or "gpt-4-vision-preview"),
                    **{k: v for k, v in rewritten_body.items() if k not in ("messages", "model", "stream")}
                ):
                    if line:
                        yield f"{line}\n\n"
                
                add_log("INFO", f"📥 流式对话返回成功" + (f" (第{attempt}次尝试)" if attempt > 1 else ""))
                return
                
            except httpx.HTTPStatusError as e:
                last_status_code = e.response.status_code
                try:
                    last_error_response = e.response.text
                    error_json = e.response.json() if hasattr(e.response, 'json') else {}
                    last_error_detail = error_json.get("error", {}).get("message", str(e))
                except:
                    last_error_detail = str(e.response.status_code)
                
                logger.warning(f"Stream error (attempt {attempt}/{max_retries}): {last_error_detail[:100]}")
                add_log("WARNING", f"⚠️ 流式错误 (尝试 {attempt}/{max_retries}): {last_error_detail[:50]}")
                
                if attempt < max_retries:
                    await asyncio.sleep(1)
                    
            except httpx.RequestError as e:
                last_error_detail = f"Connection error: {str(e)}"
                logger.warning(f"Stream connection error (attempt {attempt}/{max_retries}): {e}")
                add_log("WARNING", f"⚠️ 流式连接错误 (尝试 {attempt}/{max_retries}): {str(e)[:50]}")
                
                if attempt < max_retries:
                    await asyncio.sleep(1)
                    
            except Exception as e:
                last_error_detail = f"Unexpected error: {str(e)}"
                logger.warning(f"Stream unexpected error (attempt {attempt}/{max_retries}): {e}")
                add_log("WARNING", f"⚠️ 流式异常 (尝试 {attempt}/{max_retries}): {str(e)[:50]}")
                
                if attempt < max_retries:
                    await asyncio.sleep(1)
        
        # All retries failed
        logger.error(f"Stream: All {max_retries} attempts failed. Last error: {last_error_detail}")
        add_log("ERROR", f"❌ 流式请求: 所有 {max_retries} 次重试均失败")
        
        error_content = f"""⚠️ **上游API请求失败 (已重试{max_retries}次)**

**HTTP状态码:** {last_status_code or 'N/A'}

**错误信息:** {last_error_detail}

**完整响应:**
```
{(last_error_response or 'N/A')[:2000]}
```

请检查上游API服务是否正常运行。"""
        yield make_chunk(error_content, include_role=True)
        yield make_chunk("", finish_reason="stop")
        yield "data: [DONE]\n\n"
    
    # Choose the appropriate stream generator
    if is_image_request:
        generator = generate_interactive_stream()
    else:
        generator = generate_passthrough_stream()
    
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )



def _strip_thinking_tags(content: str) -> str:
    """
    Remove <think>...</think> blocks from AI response content.
    
    Some AI models (like DeepSeek, QwQ, etc.) include thinking/reasoning 
    in <think> tags. This function strips these for cleaner output.
    """
    import re
    # Pattern matches <think> opening tag, any content (including newlines), and </think> closing tag
    pattern = r'<think>[\s\S]*?</think>\s*'
    return re.sub(pattern, '', content, flags=re.IGNORECASE).strip()



async def _process_chat_response(
    response: Dict[str, Any],
    image_store: ImageStore,
    request: Request,
    db: AsyncSession
) -> Dict[str, Any]:
    """
    Process chat completion response, converting any base64 images to URLs.
    
    Handles multiple response formats:
    1. content as array with type: "image"
    2. content as string with base64 data URL (data:image/...)
    3. content as array with image_url containing base64
    4. Markdown image syntax with base64: ![...](data:image/...)
    5. Strips <think>...</think> blocks from responses
    """
    import re
    
    if not response.get("choices"):
        return response
    
    for choice in response.get("choices", []):
        message = choice.get("message", {})
        content = message.get("content")
        
        # CRITICAL FIX: Handle images in message.images field (OpenAI-format Gemini responses)
        # Some APIs (like Gemini via OpenAI-compatible proxies) return images in a separate "images" field
        images_field = message.get("images", [])
        if images_field:
            processed_images = []
            for img_item in images_field:
                if isinstance(img_item, dict):
                    image_url_obj = img_item.get("image_url", {})
                    if isinstance(image_url_obj, dict):
                        url = image_url_obj.get("url", "")
                    elif isinstance(image_url_obj, str):
                        url = image_url_obj
                    else:
                        url = ""
                    
                    if url.startswith("data:image"):
                        try:
                            b64_data = url.split(",", 1)[1]
                            image = await image_store.save_from_base64(b64_data)
                            public_url = await build_image_url(request, db, image.image_id)
                            
                            processed_images.append({
                                "type": "image_url",
                                "image_url": {"url": public_url}
                            })
                            logger.info(f"Saved image from images field: {public_url}")
                            add_log("INFO", f"✅ 对话图片已保存: {image.image_id[:8]}...")
                        except Exception as e:
                            logger.error(f"Failed to save image from images field: {e}")
                            processed_images.append(img_item)  # Keep original on error
                    else:
                        processed_images.append(img_item)
                else:
                    processed_images.append(img_item)
            
            # Convert to markdown string format for OpenWebUI compatibility
            # OpenWebUI expects content as string, not structured array
            if processed_images:
                markdown_parts = []
                for img in processed_images:
                    if isinstance(img, dict) and img.get("type") == "image_url":
                        url = img.get("image_url", {}).get("url", "")
                        if url:
                            markdown_parts.append(f"![image]({url})")
                
                # Build final content string
                if markdown_parts:
                    new_content = "\n".join(markdown_parts)
                    # If there was original text content, prepend it (with think tags stripped)
                    if content and isinstance(content, str):
                        cleaned_content = _strip_thinking_tags(content)
                        if cleaned_content:
                            new_content = cleaned_content + "\n" + new_content
                    
                    message["content"] = new_content
                    # Remove the images field as we've moved them to content
                    if "images" in message:
                        del message["images"]
                    continue  # Move to next choice
        
        if content is None:
            continue
        
        # Handle content as string
        if isinstance(content, str):
            # Strip <think>...</think> blocks first
            new_content = _strip_thinking_tags(content)
            processed = False
            
            # First check for markdown image syntax with base64 (more specific pattern)
            # ![alt](data:image/...)
            md_pattern = r'!\[([^\]]*)\]\((data:image/[^;]+;base64,[A-Za-z0-9+/=]+)\)'
            md_matches = list(re.finditer(md_pattern, new_content))
            
            if md_matches:
                for match in reversed(md_matches):
                    alt_text = match.group(1)
                    data_url = match.group(2)
                    b64_data = data_url.split(",", 1)[1]
                    
                    try:
                        image = await image_store.save_from_base64(b64_data)
                        image_url = await build_image_url(request, db, image.image_id)
                        
                        # Replace with URL in markdown
                        new_md = f"![{alt_text}]({image_url})"
                        new_content = new_content.replace(match.group(0), new_md)
                        processed = True
                        logger.info(f"Converted markdown base64 to URL: {image_url}")
                        add_log("INFO", f"对话图片已保存: {image.image_id[:8]}...")
                    except Exception as e:
                        logger.error(f"Failed to save markdown base64 image: {e}")
                
                message["content"] = new_content
            
            # Only check for standalone base64 data URLs if no markdown was found
            if not processed:
                # Pattern: data:image/xxx;base64,xxxxx (not inside markdown)
                base64_pattern = r'data:image/[^;]+;base64,([A-Za-z0-9+/=]+)'
                matches = list(re.finditer(base64_pattern, new_content))
                
                if matches:
                    for match in reversed(matches):  # Reverse to maintain positions
                        b64_data = match.group(1)
                        full_match = match.group(0)
                        
                        try:
                            # Save image
                            image = await image_store.save_from_base64(b64_data)
                            image_url = await build_image_url(request, db, image.image_id)
                            
                            # Replace base64 with URL
                            new_content = new_content.replace(full_match, image_url)
                            logger.info(f"Converted base64 in text to URL: {image_url}")
                        except Exception as e:
                            logger.error(f"Failed to save base64 image from text: {e}")
                    
                    message["content"] = new_content
                else:
                    # No images found, but still update content if think tags were stripped
                    if new_content != content:
                        message["content"] = new_content
        
        # Handle content as array (multimodal response)
        elif isinstance(content, list):
            new_content = []
            modified = False
            
            for item in content:
                if not isinstance(item, dict):
                    new_content.append(item)
                    continue
                
                item_type = item.get("type")
                
                # Check for image data in response
                if item_type == "image" and item.get("image"):
                    image_data = item["image"]
                    if is_base64_image(image_data):
                        try:
                            b64_data = image_data
                            if b64_data.startswith("data:"):
                                b64_data = b64_data.split(",", 1)[1]
                            
                            image = await image_store.save_from_base64(b64_data)
                            image_url = await build_image_url(request, db, image.image_id)
                            
                            new_item = {
                                "type": "image_url",
                                "image_url": {"url": image_url}
                            }
                            new_content.append(new_item)
                            modified = True
                            logger.info(f"Converted response image to URL: {image_url}")
                            continue
                        except Exception as e:
                            logger.error(f"Failed to save response image: {e}")
                
                # Check for image_url with base64 data
                elif item_type == "image_url":
                    image_url_obj = item.get("image_url", {})
                    url = image_url_obj.get("url", "")
                    
                    if url.startswith("data:image"):
                        try:
                            b64_data = url.split(",", 1)[1]
                            image = await image_store.save_from_base64(b64_data)
                            public_url = await build_image_url(request, db, image.image_id)
                            
                            new_item = {
                                "type": "image_url",
                                "image_url": {"url": public_url}
                            }
                            new_content.append(new_item)
                            modified = True
                            logger.info(f"Converted image_url base64 to URL: {public_url}")
                            continue
                        except Exception as e:
                            logger.error(f"Failed to save image_url base64: {e}")
                
                new_content.append(item)
            
            if modified:
                message["content"] = new_content
    
    return response

