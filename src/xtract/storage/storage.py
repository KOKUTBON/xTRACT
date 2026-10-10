from __future__ import annotations

import abc
from pathlib import Path


class ObjectStorageClient(abc.ABC):
    """Abstract object storage client for document blobs and artifacts."""

    @abc.abstractmethod
    def put_object(
        self,
        storage_class: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Store an object and return its canonical URI."""
        raise NotImplementedError

    @abc.abstractmethod
    def get_object(self, storage_class: str, key: str) -> bytes:
        """Retrieve an object's bytes."""
        raise NotImplementedError

    @abc.abstractmethod
    def object_exists(self, storage_class: str, key: str) -> bool:
        """Check if an object exists."""
        raise NotImplementedError

    @abc.abstractmethod
    def delete_object(self, storage_class: str, key: str) -> bool:
        """Delete an object if present."""
        raise NotImplementedError

    @abc.abstractmethod
    def list_objects(self, storage_class: str, prefix: str = "") -> list[dict]:
        """List objects in a storage class matching prefix."""
        raise NotImplementedError

    @abc.abstractmethod
    def get_uri(self, storage_class: str, key: str) -> str:
        """Get canonical URI for an object."""
        raise NotImplementedError


class LocalStorageClient(ObjectStorageClient):
    """Filesystem-backed implementation of ObjectStorageClient."""

    def __init__(self, root_dir: Path | str) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, storage_class: str, key: str) -> Path:
        clean_class = storage_class.strip("/").replace("..", "_")
        clean_key = key.strip("/").replace("..", "_")
        target = (self.root_dir / clean_class / clean_key).resolve()
        if not target.is_relative_to(self.root_dir):
            raise ValueError(f"Object key escapes the storage root: {key}")
        return target

    def put_object(
        self,
        storage_class: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        target_path = self._resolve_path(storage_class, key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_suffix(target_path.suffix + ".tmp")
        temp_path.write_bytes(data)
        temp_path.replace(target_path)
        return self.get_uri(storage_class, key)

    def get_object(self, storage_class: str, key: str) -> bytes:
        target_path = self._resolve_path(storage_class, key)
        if not target_path.is_file():
            raise FileNotFoundError(
                f"Object {key} in {storage_class} does not exist at {target_path}"
            )
        return target_path.read_bytes()

    def object_exists(self, storage_class: str, key: str) -> bool:
        return self._resolve_path(storage_class, key).is_file()

    def delete_object(self, storage_class: str, key: str) -> bool:
        target_path = self._resolve_path(storage_class, key)
        if target_path.is_file():
            target_path.unlink()
            return True
        return False

    def list_objects(self, storage_class: str, prefix: str = "") -> list[dict]:
        class_dir = self.root_dir / storage_class.strip("/").replace("..", "_")
        if not class_dir.is_dir():
            return []
        results = []
        for p in class_dir.rglob("*"):
            if p.is_file() and not p.name.endswith(".tmp"):
                rel_key = str(p.relative_to(class_dir))
                if not prefix or rel_key.startswith(prefix):
                    results.append({"key": rel_key, "size": p.stat().st_size})
        return results

    def get_uri(self, storage_class: str, key: str) -> str:
        return f"file://{self._resolve_path(storage_class, key)}"
