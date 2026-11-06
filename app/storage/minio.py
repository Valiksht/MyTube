import asyncio
from typing import BinaryIO

from minio import Minio
from minio.error import S3Error
from urllib3.response import BaseHTTPResponse

from app.core.config import Settings
from app.storage.base import StorageError


class _MinioBody:
    def __init__(self, response: BaseHTTPResponse) -> None:
        self._response = response

    def read(self, size: int = -1) -> bytes:
        chunk = self._response.read(size)
        return chunk if isinstance(chunk, bytes) else bytes(chunk)

    def close(self) -> None:
        self._response.close()
        self._response.release_conn()


class MinioStorage:
    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.minio_bucket
        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )

    async def upload(
        self,
        *,
        object_key: str,
        data: BinaryIO,
        size: int,
        content_type: str,
    ) -> None:
        await asyncio.to_thread(self._upload, object_key, data, size, content_type)

    async def delete(self, object_key: str) -> None:
        await asyncio.to_thread(self._delete, object_key)

    async def open(self, *, object_key: str, offset: int, length: int) -> _MinioBody:
        return await asyncio.to_thread(self._open, object_key, offset, length)

    def _upload(self, object_key: str, data: BinaryIO, size: int, content_type: str) -> None:
        try:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
            self._client.put_object(
                self._bucket,
                object_key,
                data,
                length=size,
                content_type=content_type,
            )
        except (S3Error, OSError) as exc:
            raise StorageError from exc

    def _delete(self, object_key: str) -> None:
        try:
            self._client.remove_object(self._bucket, object_key)
        except (S3Error, OSError) as exc:
            raise StorageError from exc

    def _open(self, object_key: str, offset: int, length: int) -> _MinioBody:
        try:
            response = self._client.get_object(
                self._bucket,
                object_key,
                offset=offset,
                length=length,
            )
        except (S3Error, OSError) as exc:
            raise StorageError from exc
        return _MinioBody(response)
