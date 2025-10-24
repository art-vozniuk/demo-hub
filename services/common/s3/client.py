import io
import os
import logging
from uuid import uuid4

import aioboto3
from botocore.config import Config as BotoConfig

from .config import config

log = logging.getLogger(__name__)


class S3Client:
    def __init__(self):
        self.boto_config = BotoConfig(
            region_name=config.S3_REGION,
            connect_timeout=30,
            read_timeout=300,
            retries={"max_attempts": 5, "mode": "adaptive"},
        )
        self.session = aioboto3.Session()

    async def _get_client(self):
        return self.session.client(
            "s3",
            aws_access_key_id=config.S3_ACCESS_KEY_ID,
            aws_secret_access_key=config.S3_ACCESS_KEY_SECRET,
            endpoint_url=config.S3_ENDPOINT,
            config=self.boto_config,
        )

    async def upload_file(
        self,
        data_bytes: bytes,
        s3_bucket: str,
        s3_folder: str,
        file_extension: str,
        file_name: str | None = None,
    ) -> str:
        async with await self._get_client() as s3:
            file = io.BytesIO(data_bytes)
            file_name = file_name or uuid4().hex
            s3_key = f"{s3_folder}/{file_name}.{file_extension}"
            await s3.upload_fileobj(Bucket=s3_bucket, Key=s3_key, Fileobj=file)
            return f"{config.S3_PUBLIC_BUCKETS_ENDPOINT}/{s3_bucket}/{s3_key}"

    async def _download_to_file(self, s3_bucket: str, s3_key: str, file):
        async with await self._get_client() as s3:
            response = await s3.get_object(Bucket=s3_bucket, Key=s3_key)
            total = response["ContentLength"]
            chunk_size = 1024 * 1024
            downloaded = 0
            last_log = 0

            while True:
                chunk = await response["Body"].read(chunk_size)
                if not chunk:
                    break
                file.write(chunk)
                downloaded += len(chunk)
                progress = int(downloaded / total * 100)
                if progress - last_log >= 10:
                    log.info(f"{s3_key}: {progress}%")
                    last_log = progress

    async def download_file(self, s3_bucket: str, s3_key: str) -> bytes:
        file = io.BytesIO()
        await self._download_to_file(s3_bucket, s3_key, file)

        file.seek(0)
        return file.read()

    async def download_file_to_disc(
        self, s3_bucket: str, s3_key: str, path: str
    ) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            await self._download_to_file(s3_bucket, s3_key, f)
