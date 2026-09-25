"""Behavioural tests for fuses.py against a temp copy of the stock Photon exe."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fuses  # noqa: E402

LOCAL = Path(os.environ["LOCALAPPDATA"])
BACKUP = LOCAL / "photon-mod" / "backup"
INSTALLED = LOCAL / "Programs" / "Photon Studio" / "Photon Studio.exe"
STOCK_WIRE = "101100011"  # Photon 0.1.21 as shipped


def stock_exe():
    backups = sorted(BACKUP.glob("Photon Studio.exe.orig-*")) if BACKUP.exists() else []
    return backups[-1] if backups else INSTALLED


class FuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.exe = Path(cls.tmp.name) / "photon.exe"
        shutil.copyfile(stock_exe(), cls.exe)
        cls.stock = cls.exe.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.exe.write_bytes(self.stock)

    def test_read_reports_stock_wire(self):
        self.assertEqual(fuses.read(self.exe)["wire"], STOCK_WIRE)
        self.assertTrue(fuses.read(self.exe)["fuses"]["RunAsNode"])

    def test_set_changes_only_requested_fuse_bytes(self):
        fuses.set_fuses(self.exe, {"RunAsNode": False, "OnlyLoadAppFromAsar": True})
        self.assertEqual(fuses.read(self.exe)["wire"], "001101011")
        after = self.exe.read_bytes()
        self.assertEqual(len(after), len(self.stock))
        self.assertEqual(sum(a != b for a, b in zip(after, self.stock)), 2)

    def test_unknown_fuse_is_rejected_and_file_untouched(self):
        with self.assertRaises(fuses.FuseError):
            fuses.set_fuses(self.exe, {"NoSuchFuse": True})
        self.assertEqual(self.exe.read_bytes(), self.stock)

    def test_file_without_sentinel_is_rejected(self):
        plain = Path(self.tmp.name) / "plain.bin"
        plain.write_bytes(b"\0" * 4096)
        with self.assertRaises(fuses.FuseError):
            fuses.read(plain)

    def test_repo_config_hardens_stock(self):
        fuses.set_fuses(self.exe, fuses.load_config())
        state = fuses.read(self.exe)["fuses"]
        self.assertFalse(state["RunAsNode"])
        self.assertFalse(state["EnableNodeOptionsEnvironmentVariable"])
        self.assertFalse(state["EnableNodeCliInspectArguments"])
        self.assertFalse(state["EnableEmbeddedAsarIntegrityValidation"])
        self.assertTrue(state["OnlyLoadAppFromAsar"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
