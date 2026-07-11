from dataclasses import dataclass
import json

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from .config import get_settings


@dataclass
class StoredObject:
    bucket_name: str
    object_key: str
    etag: str | None


class RustFSStorageClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.rustfs_endpoint,
            aws_access_key_id=settings.rustfs_access_key,
            aws_secret_access_key=settings.rustfs_secret_key,
            region_name=settings.aws_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def ensure_bucket(self, bucket_name: str) -> None:
        try:
            self._client.head_bucket(Bucket=bucket_name)
        except ClientError:
            self._client.create_bucket(Bucket=bucket_name)

    def upload_bytes(
        self,
        *,
        bucket_name: str,
        object_key: str,
        payload: bytes,
        content_type: str,
        metadata: dict[str, str] | None = None,
    ) -> StoredObject:
        response = self._client.put_object(
            Bucket=bucket_name,
            Key=object_key,
            Body=payload,
            ContentType=content_type,
            Metadata=self._sanitize_metadata(metadata),
        )
        return StoredObject(
            bucket_name=bucket_name,
            object_key=object_key,
            etag=response.get("ETag"),
        )

    @staticmethod
    def _sanitize_metadata(metadata: dict[str, str] | None) -> dict[str, str]:
        if not metadata:
            return {}

        sanitized: dict[str, str] = {}
        for key, value in metadata.items():
            safe_key = key.encode("ascii", errors="ignore").decode("ascii") or "meta"
            safe_value = json.dumps(str(value), ensure_ascii=True)[1:-1]
            sanitized[safe_key] = safe_value
        return sanitized

    def upload_json(
        self,
        *,
        bucket_name: str,
        object_key: str,
        payload: dict | list,
        metadata: dict[str, str] | None = None,
    ) -> StoredObject:
        return self.upload_bytes(
            bucket_name=bucket_name,
            object_key=object_key,
            payload=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            content_type="application/json",
            metadata=metadata,
        )

    def download_bytes(self, *, bucket_name: str, object_key: str) -> bytes:
        response = self._client.get_object(Bucket=bucket_name, Key=object_key)
        return response["Body"].read()

    def delete_object(self, *, bucket_name: str, object_key: str) -> None:
        self._client.delete_object(Bucket=bucket_name, Key=object_key)
