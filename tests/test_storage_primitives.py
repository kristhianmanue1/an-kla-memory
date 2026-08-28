from __future__ import annotations

import errno
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from an_kla.storage_primitives import (
    StorageOperationError,
    atomic_write,
    fsync_directory,
    fsync_file,
)


class PrimitiveFaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _atomic(self) -> None:
        atomic_write(self.root / "target", b"payload", fsync_directory=lambda _p: None)

    def test_atomic_points_have_stable_codes(self) -> None:
        cases = (
            ("os.open", "temporary_open_failed", OSError(errno.EIO, "open")),
            ("os.write", "temporary_write_failed", OSError(errno.ENOSPC, "write")),
            ("os.fsync", "temporary_fsync_failed", OSError(errno.EIO, "fsync")),
            ("os.replace", "replace_failed", OSError(errno.ENOSPC, "replace")),
        )
        for target, code, error in cases:
            with self.subTest(target=target):
                with patch(f"an_kla.storage_primitives.{target}", side_effect=error):
                    with self.assertRaises(StorageOperationError) as raised:
                        self._atomic()
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(raised.exception.cause.errno, error.errno)

    def test_zero_write_is_terminal(self) -> None:
        with patch("an_kla.storage_primitives.os.write", return_value=0):
            with self.assertRaises(StorageOperationError) as raised:
                self._atomic()
        self.assertEqual(raised.exception.code, "temporary_write_failed")

    def test_primary_error_survives_close_and_cleanup_errors(self) -> None:
        with patch(
            "an_kla.storage_primitives.os.fsync",
            side_effect=OSError(errno.EIO, "primary"),
        ), patch(
            "an_kla.storage_primitives.os.close",
            side_effect=OSError(errno.ENOSPC, "close"),
        ), patch.object(
            Path,
            "unlink",
            side_effect=OSError(errno.ENOSPC, "cleanup"),
        ):
            with self.assertRaises(StorageOperationError) as raised:
                self._atomic()
        self.assertEqual(raised.exception.code, "temporary_fsync_failed")
        self.assertTrue(raised.exception.close_incomplete)
        self.assertTrue(raised.exception.cleanup_incomplete)

    @unittest.skipIf(
        os.name == "nt",
        "fsync_directory es no-op en NT (sin dir-fsync en Windows)",
    )
    def test_directory_fsync_points_do_not_mask_primary(self) -> None:
        with patch(
            "an_kla.storage_primitives.os.fsync",
            side_effect=OSError(errno.EIO, "primary"),
        ), patch(
            "an_kla.storage_primitives.os.close",
            side_effect=OSError(errno.ENOSPC, "close"),
        ):
            with self.assertRaises(StorageOperationError) as raised:
                fsync_directory(self.root)
        self.assertEqual(raised.exception.code, "directory_fsync_failed")
        self.assertTrue(raised.exception.close_incomplete)

    def test_file_fsync_open_and_close_codes(self) -> None:
        target = self.root / "existing"
        target.write_bytes(b"x")
        with patch(
            "an_kla.storage_primitives.os.open",
            side_effect=OSError(errno.EIO, "open"),
        ):
            with self.assertRaises(StorageOperationError) as opened:
                fsync_file(target)
        self.assertEqual(opened.exception.code, "file_open_failed")

        with patch(
            "an_kla.storage_primitives.os.close",
            side_effect=OSError(errno.EIO, "close"),
        ):
            with self.assertRaises(StorageOperationError) as closed:
                fsync_file(target)
        self.assertEqual(closed.exception.code, "file_close_failed")


if __name__ == "__main__":
    unittest.main()
