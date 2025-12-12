"""
PicGate Cloudflare R2 Client Service
S3-compatible storage for long-term image archival.

Uses boto3 with Cloudflare R2 endpoint.
"""

import logging
import asyncio
from typing import Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Thread pool for blocking boto3 operations
_executor = ThreadPoolExecutor(max_workers=4)


class R2Client:
    """
    Cloudflare R2 client for S3-compatible operations.
    
    R2 Endpoint format: https://{account_id}.r2.cloudflarestorage.com
    Objects are stored with key format: openwebui/{image_id}.png
    """
    
    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str
    ):
        self.bucket_name = bucket_name
        self.endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
        
        # Create boto3 S3 client with R2 configuration
        self._client = boto3.client(
            's3',
            endpoint_url=self.endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(
                signature_version='s3v4',
                retries={'max_attempts': 3, 'mode': 'standard'}
            ),
            region_name='auto'  # R2 uses 'auto' region
        )
        
        logger.info(f"R2 client initialized for bucket: {bucket_name}")
    
    def _run_sync(self, func, *args, **kwargs):
        """Run a synchronous function in the thread pool."""
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(_executor, lambda: func(*args, **kwargs))
    
    async def upload_image(
        self,
        image_id: str,
        image_bytes: bytes,
        content_type: str = "image/png"
    ) -> Tuple[bool, Optional[str]]:
        """
        Upload an image to R2.
        
        Args:
            image_id: UUID of the image
            image_bytes: Raw image data
            content_type: MIME type of the image
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        key = f"openwebui/{image_id}.png"
        
        try:
            await self._run_sync(
                self._client.put_object,
                Bucket=self.bucket_name,
                Key=key,
                Body=image_bytes,
                ContentType=content_type
            )
            logger.info(f"Uploaded image {image_id} to R2 ({len(image_bytes)} bytes)")
            return True, None
            
        except ClientError as e:
            error_msg = str(e)
            logger.error(f"R2 upload failed for {image_id}: {error_msg}")
            return False, error_msg
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Unexpected R2 upload error for {image_id}: {error_msg}")
            return False, error_msg
    
    async def download_image(self, image_id: str) -> Tuple[Optional[bytes], Optional[str]]:
        """
        Download an image from R2.
        
        Args:
            image_id: UUID of the image
            
        Returns:
            Tuple of (image_bytes: Optional[bytes], error_message: Optional[str])
        """
        key = f"openwebui/{image_id}.png"
        
        try:
            response = await self._run_sync(
                self._client.get_object,
                Bucket=self.bucket_name,
                Key=key
            )
            # Read the body synchronously (it's a StreamingBody)
            image_bytes = await self._run_sync(response['Body'].read)
            logger.info(f"Downloaded image {image_id} from R2 ({len(image_bytes)} bytes)")
            return image_bytes, None
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == 'NoSuchKey':
                logger.warning(f"Image {image_id} not found in R2")
                return None, "Image not found in R2"
            error_msg = str(e)
            logger.error(f"R2 download failed for {image_id}: {error_msg}")
            return None, error_msg
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Unexpected R2 download error for {image_id}: {error_msg}")
            return None, error_msg
    
    async def delete_image(self, image_id: str) -> Tuple[bool, Optional[str]]:
        """
        Delete an image from R2.
        
        Args:
            image_id: UUID of the image
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        key = f"openwebui/{image_id}.png"
        
        try:
            await self._run_sync(
                self._client.delete_object,
                Bucket=self.bucket_name,
                Key=key
            )
            logger.info(f"Deleted image {image_id} from R2")
            return True, None
            
        except ClientError as e:
            error_msg = str(e)
            logger.error(f"R2 delete failed for {image_id}: {error_msg}")
            return False, error_msg
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Unexpected R2 delete error for {image_id}: {error_msg}")
            return False, error_msg
    
    async def check_exists(self, image_id: str) -> bool:
        """
        Check if an image exists in R2.
        
        Args:
            image_id: UUID of the image
            
        Returns:
            True if image exists, False otherwise
        """
        key = f"openwebui/{image_id}.png"
        
        try:
            await self._run_sync(
                self._client.head_object,
                Bucket=self.bucket_name,
                Key=key
            )
            return True
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == '404' or error_code == 'NoSuchKey':
                return False
            logger.error(f"R2 check_exists failed for {image_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected R2 check_exists error for {image_id}: {e}")
            return False


def create_r2_client(settings) -> Optional[R2Client]:
    """
    Factory function to create an R2 client from settings.
    
    Returns None if R2 is not configured.
    """
    if not all([
        settings.r2_account_id,
        settings.r2_access_key_id,
        settings.r2_secret_access_key,
        settings.r2_bucket_name
    ]):
        logger.debug("R2 not configured - missing credentials")
        return None
    
    return R2Client(
        account_id=settings.r2_account_id,
        access_key_id=settings.r2_access_key_id,
        secret_access_key=settings.r2_secret_access_key,
        bucket_name=settings.r2_bucket_name
    )
