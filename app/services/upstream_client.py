"""
PicGate Upstream OpenAI Client
Handles communication with upstream AI image generation APIs.
"""

import httpx
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class UpstreamClient:
    """Client for communicating with upstream OpenAI-compatible APIs."""
    
    def __init__(self, api_base: str, api_key: str, timeout: float = 600.0):
        """
        Initialize the upstream client.
        
        Args:
            api_base: Base URL for the API (e.g., https://api.openai.com/v1)
            api_key: API key for authentication
            timeout: Request timeout in seconds
        """
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        
    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    async def generate_image(
        self,
        prompt: str,
        model: str,
        n: int = 1,
        size: str = "1024x1024",
        quality: str = "standard",
        style: str = "vivid",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate images from text prompt.
        
        Always requests base64 format (b64_json) for consistent handling.
        
        Returns:
            Response dict with 'created' and 'data' containing base64 images
        """
        url = f"{self.api_base}/images/generations"
        
        payload = {
            "prompt": prompt,
            "model": model,
            "n": n,
            "size": size,
            "response_format": "b64_json",  # Always request base64
        }
        
        # Add optional parameters if provided
        if quality:
            payload["quality"] = quality
        if style:
            payload["style"] = style
            
        # Add any extra parameters (for flexibility with different APIs)
        for key, value in kwargs.items():
            if value is not None:
                payload[key] = value
        
        logger.info(f"Generating image with prompt: {prompt[:50]}...")
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                url,
                json=payload,
                headers=self._get_headers()
            )
            
            if response.status_code != 200:
                logger.error(f"Upstream error: {response.status_code} - {response.text}")
                response.raise_for_status()
            
            return response.json()
    
    async def edit_image(
        self,
        image_base64: str,
        prompt: str,
        model: str,
        mask_base64: Optional[str] = None,
        n: int = 1,
        size: str = "1024x1024",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Edit/modify an existing image.
        
        Args:
            image_base64: Base64-encoded source image
            prompt: Edit instructions
            model: Model name
            mask_base64: Optional base64-encoded mask
            
        Returns:
            Response dict with 'created' and 'data' containing base64 images
        """
        url = f"{self.api_base}/images/edits"
        
        payload = {
            "image": image_base64,
            "prompt": prompt,
            "model": model,
            "n": n,
            "size": size,
            "response_format": "b64_json",
        }
        
        if mask_base64:
            payload["mask"] = mask_base64
            
        for key, value in kwargs.items():
            if value is not None:
                payload[key] = value
        
        logger.info(f"Editing image with prompt: {prompt[:50]}...")
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                url,
                json=payload,
                headers=self._get_headers()
            )
            
            if response.status_code != 200:
                logger.error(f"Upstream error: {response.status_code} - {response.text}")
                response.raise_for_status()
            
            return response.json()
    
    async def chat_completions(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Send chat completion request (non-streaming).
        Used for multi-modal conversations with images.
        
        Args:
            messages: Chat messages array
            model: Model name
            
        Returns:
            Chat completion response
        """
        url = f"{self.api_base}/chat/completions"
        
        payload = {
            "messages": messages,
            "model": model,
            "stream": False,  # Always non-streaming
        }
        
        for key, value in kwargs.items():
            if value is not None:
                payload[key] = value
        
        logger.info(f"Chat completion with {len(messages)} messages")
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                url,
                json=payload,
                headers=self._get_headers()
            )
            
            if response.status_code != 200:
                logger.error(f"Upstream error: {response.status_code} - {response.text}")
                response.raise_for_status()
            
            return response.json()
    
    async def chat_completions_stream(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        **kwargs
    ):
        """
        Send streaming chat completion request.
        Yields SSE data lines as they arrive from upstream.
        
        Args:
            messages: Chat messages array
            model: Model name
            
        Yields:
            Raw SSE data lines (bytes)
        """
        url = f"{self.api_base}/chat/completions"
        
        payload = {
            "messages": messages,
            "model": model,
            "stream": True,
        }
        
        for key, value in kwargs.items():
            if value is not None:
                payload[key] = value
        
        logger.info(f"Streaming chat completion with {len(messages)} messages")
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                url,
                json=payload,
                headers=self._get_headers()
            ) as response:
                if response.status_code != 200:
                    # Read error response
                    error_body = await response.aread()
                    logger.error(f"Upstream stream error: {response.status_code} - {error_body}")
                    response.raise_for_status()
                
                # Yield lines as they come
                async for line in response.aiter_lines():
                    if line:
                        yield line

