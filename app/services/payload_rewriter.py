"""
PicGate Payload Rewriter Service
Deep JSON traversal to convert all image URLs to base64 before sending to upstream.

This is a CRITICAL component that ensures:
1. All image URLs in requests are converted to base64 for upstream AI models
2. AI models receive base64 data, not URLs (they can't "see" URLs)
3. Local PicGate images are loaded from storage
4. External images are optionally fetched (if allowed by settings)
"""

import re
import httpx
import logging
import base64
from typing import Any, Dict, Optional, Set
from copy import deepcopy

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.image_store import ImageStore, extract_image_id_from_url, is_base64_image

logger = logging.getLogger(__name__)


class PayloadRewriter:
    """
    Deep JSON rewriter that converts all image URLs to base64.
    
    Handles:
    - `image`, `init_image`, `mask` fields
    - messages[].content[] with type: "image_url"  
    - messages[].content[] with type: "input_image"
    - Nested tool_calls/function_call arguments
    """
    
    def __init__(
        self,
        db: AsyncSession,
        public_base_url: str = "",
        allow_external_fetch: bool = False
    ):
        self.db = db
        self.public_base_url = public_base_url
        self.allow_external_fetch = allow_external_fetch
        self.image_store = ImageStore(db)
        
        # Cache for URL -> base64 conversions (deduplication within same request)
        self._url_cache: Dict[str, str] = {}
        
        # Track processed URLs for logging
        self._processed_urls: Set[str] = set()
    
    async def rewrite(self, payload: Any) -> Any:
        """
        Rewrite the entire payload, converting all image URLs to base64.
        
        Args:
            payload: Any JSON-compatible structure (dict, list, or primitive)
            
        Returns:
            Rewritten payload with URLs replaced by base64 data
        """
        self._url_cache.clear()
        self._processed_urls.clear()
        
        result = await self._rewrite_value(payload)
        
        if self._processed_urls:
            logger.info(f"Rewrote {len(self._processed_urls)} image URLs to base64")
        
        return result
    
    async def _rewrite_value(self, value: Any) -> Any:
        """Recursively rewrite a value."""
        if isinstance(value, dict):
            return await self._rewrite_dict(value)
        elif isinstance(value, list):
            return await self._rewrite_list(value)
        else:
            return value
    
    async def _rewrite_dict(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """Rewrite a dictionary, handling special image fields."""
        result = {}
        
        for key, value in d.items():
            # Check for special image fields
            if key in ("image", "init_image", "mask"):
                result[key] = await self._convert_image_field(value)
            
            # Handle OpenAI chat message content array
            elif key == "content" and isinstance(value, list):
                result[key] = await self._rewrite_content_array(value)
            
            # Handle tool_calls and function_call arguments (may contain JSON strings)
            elif key == "arguments" and isinstance(value, str):
                result[key] = await self._rewrite_json_string(value)
            
            # Handle tool_calls array
            elif key == "tool_calls" and isinstance(value, list):
                result[key] = await self._rewrite_list(value)
            
            # Recursively process nested structures
            else:
                result[key] = await self._rewrite_value(value)
        
        return result
    
    async def _rewrite_list(self, lst: list) -> list:
        """Rewrite a list."""
        return [await self._rewrite_value(item) for item in lst]
    
    async def _rewrite_content_array(self, content: list) -> list:
        """
        Rewrite a chat message content array.
        
        Handles formats like:
        - {"type": "image_url", "image_url": {"url": "..."}}
        - {"type": "input_image", "input_image": {"url": "..."}}
        - {"type": "image", "image": "..."}
        """
        result = []
        
        for item in content:
            if not isinstance(item, dict):
                result.append(item)
                continue
            
            item_type = item.get("type")
            
            if item_type == "image_url":
                # Standard OpenAI format
                image_url_obj = item.get("image_url", {})
                url = image_url_obj.get("url", "")
                
                if url and not is_base64_image(url):
                    base64_data = await self._url_to_base64(url)
                    if base64_data:
                        # Create new item with base64 data
                        new_item = deepcopy(item)
                        new_item["image_url"]["url"] = f"data:image/png;base64,{base64_data}"
                        result.append(new_item)
                        continue
                
                result.append(item)
            
            elif item_type == "input_image":
                # Alternative format
                input_image_obj = item.get("input_image", {})
                url = input_image_obj.get("url", "")
                
                if url and not is_base64_image(url):
                    base64_data = await self._url_to_base64(url)
                    if base64_data:
                        new_item = deepcopy(item)
                        new_item["input_image"]["url"] = f"data:image/png;base64,{base64_data}"
                        result.append(new_item)
                        continue
                
                result.append(item)
            
            elif item_type == "image":
                # Direct image field
                image_data = item.get("image", "")
                if image_data and not is_base64_image(image_data):
                    base64_data = await self._url_to_base64(image_data)
                    if base64_data:
                        new_item = deepcopy(item)
                        new_item["image"] = base64_data
                        result.append(new_item)
                        continue
                
                result.append(item)
            
            else:
                # Recursively process other types
                result.append(await self._rewrite_value(item))
        
        return result
    
    async def _rewrite_json_string(self, json_str: str) -> str:
        """
        Rewrite a JSON string that may contain image URLs.
        Used for tool_calls arguments.
        """
        import json
        
        try:
            data = json.loads(json_str)
            rewritten = await self._rewrite_value(data)
            return json.dumps(rewritten)
        except json.JSONDecodeError:
            # Not valid JSON, return as-is
            return json_str
    
    async def _convert_image_field(self, value: Any) -> Any:
        """Convert an image field value (URL or base64) to base64."""
        if not isinstance(value, str):
            return value
        
        if is_base64_image(value):
            # Already base64, return as-is
            return value
        
        # It's a URL, convert to base64
        base64_data = await self._url_to_base64(value)
        if base64_data:
            return base64_data
        
        # Failed to convert, return original
        return value
    
    async def _url_to_base64(self, url: str) -> Optional[str]:
        """
        Convert an image URL to base64 data.
        
        Handles:
        1. Local PicGate URLs (/images/{id})
        2. External URLs (if allow_external_fetch is True)
        
        Uses caching to avoid duplicate downloads.
        """
        url = url.strip()
        
        if not url:
            return None
        
        # Check cache first
        if url in self._url_cache:
            return self._url_cache[url]
        
        # Try to extract PicGate image ID
        image_id = await extract_image_id_from_url(url, self.public_base_url)
        
        if image_id:
            # This is a local PicGate image
            base64_data = await self._load_local_image(image_id)
            if base64_data:
                self._url_cache[url] = base64_data
                self._processed_urls.add(url)
                return base64_data
        
        # External URL
        if not self.allow_external_fetch:
            logger.warning(f"External image fetch not allowed for URL: {url[:100]}")
            raise ValueError(
                f"External image fetching is disabled. URL: {url[:50]}... "
                "Enable 'allow_external_image_fetch' in settings if needed."
            )
        
        # Fetch external image
        base64_data = await self._fetch_external_image(url)
        if base64_data:
            self._url_cache[url] = base64_data
            self._processed_urls.add(url)
            return base64_data
        
        return None
    
    async def _load_local_image(self, image_id: str) -> Optional[str]:
        """Load a local PicGate image as base64."""
        try:
            base64_data = await self.image_store.get_base64(image_id)
            if base64_data:
                logger.debug(f"Loaded local image {image_id}")
                return base64_data
            else:
                logger.warning(f"Local image {image_id} not found")
                return None
        except Exception as e:
            logger.error(f"Failed to load local image {image_id}: {e}")
            return None
    
    async def _fetch_external_image(self, url: str) -> Optional[str]:
        """Fetch an external image and convert to base64."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                
                # Check content type
                content_type = response.headers.get("content-type", "")
                if not content_type.startswith("image/"):
                    logger.warning(f"URL does not return an image: {url[:100]}")
                    return None
                
                # Convert to base64
                base64_data = base64.b64encode(response.content).decode('utf-8')
                logger.info(f"Fetched external image from {url[:50]}... ({len(response.content)} bytes)")
                return base64_data
                
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch external image: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching external image: {e}")
            return None


async def create_rewriter(db: AsyncSession, settings) -> PayloadRewriter:
    """Factory function to create a PayloadRewriter with current settings."""
    return PayloadRewriter(
        db=db,
        public_base_url=settings.public_base_url or "",
        allow_external_fetch=settings.allow_external_image_fetch
    )
