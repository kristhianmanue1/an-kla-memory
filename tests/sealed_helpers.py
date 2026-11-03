"""Shared sealed matrix fixtures; each call owns a fresh store/adapter."""
from __future__ import annotations
import types
from pathlib import Path
from an_kla.store import MemoryStore
from an_kla.sealed import bundle as sb
from an_kla.sealed.cli_dispatch import dispatch_export_create

def _cryptography_importable() -> bool:
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return False
    return True


def _make_store(root: Path) -> MemoryStore:
    source = root / "source"
    source.mkdir()
    store = MemoryStore(source)
    initial = store.initialize()
    store.commit(
        expected_current_hash=initial,
        checkpoint_patch={},
        facts=[{"id": "f-matrix", "payload": {"text": "matrix"}}],
    )
    return store


class FakeAdapterB64:
    """Adaptador determinístico en memoria (misma superficie del runner
    T3; wrap/unwrap DOC con KEK fija, blob b64 canónico §4)."""

    ADAPTER_ID = "matrix-adapter-v1"

    def __init__(self, kek: bytes = b"m" * 32) -> None:
        self._kek = kek
        self._ceks: dict[str, bytes] = {}
        self._counter = 0

    def wrap_cek(self, cek: bytes):
        import base64
        from an_kla.sealed.cek import wrap_cek

        self._counter += 1
        token = f"m{self._counter}"
        self._ceks[token] = bytes(cek)
        blob = token.encode("ascii") + b":" + wrap_cek(cek, self._kek).blob
        return types.SimpleNamespace(
            wrapped_cek=base64.b64encode(blob).decode("ascii"),
            adapter_id=self.ADAPTER_ID,
        )

    def unwrap_cek(self, wrapped_cek: str):
        import base64
        from an_kla.sealed.cek import unwrap_cek

        try:
            token, blob = base64.b64decode(
                wrapped_cek, validate=True).split(b":", 1)
            cek = unwrap_cek(blob, self._kek)
        except Exception as exc:
            raise sb.SealedPayloadAuthFailedError(
                "sealed payload authentication failed (no further detail)"
            ) from exc
        if token.decode("ascii") not in self._ceks:
            raise sb.SealedPayloadAuthFailedError(
                "sealed payload authentication failed (no further detail)"
            )
        return types.SimpleNamespace(cek=cek)


def _create_sealed(store: MemoryStore, bundle: Path) -> tuple[dict, FakeAdapterB64]:
    adapter = FakeAdapterB64()
    result = dispatch_export_create(
        store, bundle, seal=sb.SEALED_PROFILE, key_adapter="unused",
        key_adapter_args=(), _runner_override=adapter,
    )
    return result, adapter
