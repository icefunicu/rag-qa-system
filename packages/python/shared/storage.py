from __future__ import annotations

import os
from logging import getLogger
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError
from botocore.config import Config


logger = getLogger(__name__)


@dataclass(frozen=True)
class ObjectStorageSettings:
    endpoint: str
    public_endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    region: str
    secure: bool


def load_object_storage_settings(prefix: str = "OBJECT_STORAGE") -> ObjectStorageSettings:
    """Load object storage configuration from environment variables."""
    endpoint = os.getenv(f"{prefix}_ENDPOINT", "http://minio:9000").strip().rstrip("/")
    public_endpoint = os.getenv(f"{prefix}_PUBLIC_ENDPOINT", endpoint).strip().rstrip("/")
    region = os.getenv(f"{prefix}_REGION", "us-east-1").strip() or "us-east-1"
    return ObjectStorageSettings(
        endpoint=endpoint,
        public_endpoint=public_endpoint or endpoint,
        access_key=os.getenv(f"{prefix}_ACCESS_KEY", "minioadmin").strip() or "minioadmin",
        secret_key=os.getenv(f"{prefix}_SECRET_KEY", "minioadmin").strip() or "minioadmin",
        bucket=os.getenv(f"{prefix}_BUCKET", "rag-assets").strip() or "rag-assets",
        region=region,
        secure=endpoint.startswith("https://"),
    )


class ObjectStorageClient:
    """Minimal multipart upload helper for MinIO/S3-compatible storage."""

    def __init__(self, settings: ObjectStorageSettings | None = None):
        self.settings = settings or load_object_storage_settings()
        self._internal = self._create_client(self.settings.endpoint)
        self._public = self._create_client(self.settings.public_endpoint)

    def ensure_bucket(self) -> None:
        buckets = self._internal.list_buckets().get("Buckets", [])
        if not any(item.get("Name") == self.settings.bucket for item in buckets):
            self._internal.create_bucket(Bucket=self.settings.bucket)
        self._ensure_cors()

    def check_bucket_access(self) -> None:
        """Verify that the configured bucket exists and is readable.

        Failure:
        - Raises RuntimeError when the bucket is missing or the storage backend
          is not reachable with the current credentials.
        """
        try:
            self._internal.head_bucket(Bucket=self.settings.bucket)
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code") or "")
            if error_code in {"404", "NoSuchBucket", "NotFound"}:
                raise RuntimeError(f"object storage bucket does not exist: {self.settings.bucket}") from exc
            raise RuntimeError(
                f"object storage bucket is not accessible: {error_code or 'client_error'}"
            ) from exc

    def create_multipart_upload(self, storage_key: str, *, metadata: dict[str, str] | None = None) -> str:
        result = self._internal.create_multipart_upload(
            Bucket=self.settings.bucket,
            Key=storage_key,
            Metadata=metadata or {},
        )
        return str(result["UploadId"])

    def presign_upload_part(self, storage_key: str, upload_id: str, part_number: int, *, expires_in: int = 3600) -> str:
        return str(
            self._public.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": self.settings.bucket,
                    "Key": storage_key,
                    "UploadId": upload_id,
                    "PartNumber": int(part_number),
                },
                ExpiresIn=expires_in,
            )
        )

    def presign_get_object(self, storage_key: str, *, expires_in: int = 3600) -> str:
        return str(
            self._public.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.settings.bucket,
                    "Key": storage_key,
                },
                ExpiresIn=expires_in,
            )
        )

    def presign_download_url(self, storage_key: str, *, expires_in: int = 3600) -> str:
        return str(
            self._public.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.settings.bucket,
                    "Key": storage_key,
                },
                ExpiresIn=expires_in,
            )
        )

    def list_parts(self, storage_key: str, upload_id: str) -> list[dict[str, Any]]:
        response = self._internal.list_parts(
            Bucket=self.settings.bucket,
            Key=storage_key,
            UploadId=upload_id,
        )
        return list(response.get("Parts", []) or [])

    def complete_multipart_upload(
        self,
        storage_key: str,
        upload_id: str,
        parts: list[dict[str, Any]],
    ) -> None:
        self._internal.complete_multipart_upload(
            Bucket=self.settings.bucket,
            Key=storage_key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )

    def abort_multipart_upload(self, storage_key: str, upload_id: str) -> None:
        try:
            self._internal.abort_multipart_upload(
                Bucket=self.settings.bucket,
                Key=storage_key,
                UploadId=upload_id,
            )
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code") or "")
            if error_code in {"NoSuchUpload", "404", "NotFound"}:
                return
            raise

    def stat_object(self, storage_key: str) -> dict[str, Any]:
        return dict(
            self._internal.head_object(
                Bucket=self.settings.bucket,
                Key=storage_key,
            )
        )

    def delete_object(self, storage_key: str) -> None:
        try:
            self._internal.delete_object(
                Bucket=self.settings.bucket,
                Key=storage_key,
            )
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code") or "")
            if error_code in {"NoSuchKey", "404", "NotFound"}:
                return
            raise

    def put_bytes(
        self,
        storage_key: str,
        body: bytes,
        *,
        metadata: dict[str, str] | None = None,
        content_type: str | None = None,
    ) -> None:
        self._internal.put_object(
            Bucket=self.settings.bucket,
            Key=storage_key,
            Body=body,
            Metadata=metadata or {},
            ContentType=content_type or "application/octet-stream",
        )

    def download_file(self, storage_key: str, target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        self._internal.download_file(self.settings.bucket, storage_key, str(target_path))

    def get_object_bytes(self, storage_key: str) -> tuple[bytes, str]:
        response = self._internal.get_object(Bucket=self.settings.bucket, Key=storage_key)
        body = response["Body"].read()
        content_type = str(response.get("ContentType") or "application/octet-stream")
        return body, content_type

    def build_storage_key(self, *, service: str, document_id: str, file_name: str) -> str:
        safe_name = (file_name or "source.bin").replace("\\", "_").replace("/", "_")
        return f"{service}/{document_id}/{safe_name}"

    def _create_client(self, endpoint_url: str) -> BaseClient:
        return boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=self.settings.access_key,
            aws_secret_access_key=self.settings.secret_key,
            region_name=self.settings.region,
            use_ssl=endpoint_url.startswith("https://"),
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def _ensure_cors(self) -> None:
        origins = [item.strip() for item in os.getenv("OBJECT_STORAGE_ALLOWED_ORIGINS", "*").split(",") if item.strip()]
        try:
            self._internal.put_bucket_cors(
                Bucket=self.settings.bucket,
                CORSConfiguration={
                    "CORSRules": [
                        {
                            "AllowedHeaders": ["*"],
                            "AllowedMethods": ["GET", "PUT", "POST", "HEAD"],
                            "AllowedOrigins": origins or ["*"],
                            "ExposeHeaders": ["ETag"],
                            "MaxAgeSeconds": 3600,
                        }
                    ]
                },
            )
        except ClientError as exc:
            error_code = str(exc.response.get("Error", {}).get("Code") or "")
            if error_code == "NotImplemented":
                logger.warning("bucket CORS configuration is not supported by the current object storage backend; continuing without CORS")
                return
            raise
