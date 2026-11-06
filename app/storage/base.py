from typing import BinaryIO, Protocol


class StorageError(Exception):
    def __init__(self) -> None:
        super().__init__("Video storage is unavailable")


class BinaryReader(Protocol):
    def read(self, size: int = -1) -> bytes: ...

    def close(self) -> None: ...


class ObjectStorage(Protocol):
    async def upload(
        self,
        *,
        object_key: str,
        data: BinaryIO,
        size: int,
        content_type: str,
    ) -> None: ...

    async def delete(self, object_key: str) -> None: ...

    async def open(self, *, object_key: str, offset: int, length: int) -> BinaryReader: ...
