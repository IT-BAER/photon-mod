"""Behavioural tests for asar.py against the installed vendor app.asar (read-only fixture)."""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asar  # noqa: E402

FIXTURE = Path(os.environ.get(
    "PHOTON_ASAR",
    Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Photon Studio" / "resources" / "app.asar",
))
BACKUP = Path(os.environ["LOCALAPPDATA"]) / "photon-mod" / "backup"


def stock_asar():
    """Prefer the pristine backup, because the installed file may already be patched."""
    backups = sorted(BACKUP.glob("app.asar.orig-*")) if BACKUP.exists() else []
    return backups[-1] if backups else FIXTURE


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


MAIN = "dist-electron/electron/main.js"


class AsarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = stock_asar()
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def out(self, name):
        return Path(self.tmp.name) / name

    def test_apply_without_patches_is_byte_identical(self):
        dst = self.out("identity.asar")
        asar.apply(self.src, dst, [])
        self.assertEqual(sha256(self.src), sha256(dst))

    def test_patch_changes_target_and_keeps_other_files(self):
        dst = self.out("patched.asar")
        patch = {"id": "t", "file": MAIN, "edits": [
            {"find": "// electron/feedback.ts", "replace": "// electron/feedback.ts /* photon-mod test */", "count": 1}]}
        asar.apply(self.src, dst, [patch])
        text = asar.read_file(dst, MAIN).decode("utf-8")
        self.assertIn("/* photon-mod test */", text)
        self.assertEqual(asar.read_file(self.src, "package.json"), asar.read_file(dst, "package.json"))
        src_unpacked = sorted(p for p, e in asar.entries(self.src) if e.get("unpacked"))
        dst_unpacked = sorted(p for p, e in asar.entries(dst) if e.get("unpacked"))
        self.assertEqual(src_unpacked, dst_unpacked)
        self.assertTrue(src_unpacked)

    def test_patched_file_integrity_matches_new_content(self):
        dst = self.out("integrity.asar")
        patch = {"id": "t", "file": MAIN, "edits": [
            {"find": "// electron/feedback.ts", "replace": "// electron/feedback.ts /* x */", "count": 1}]}
        asar.apply(self.src, dst, [patch])
        entry = dict(asar.entries(dst))[MAIN]
        data = asar.read_file(dst, MAIN)
        self.assertEqual(entry["size"], len(data))
        self.assertEqual(entry["integrity"]["hash"], hashlib.sha256(data).hexdigest())
        blocks = [hashlib.sha256(data[i:i + 4194304]).hexdigest() for i in range(0, len(data), 4194304)]
        self.assertEqual(entry["integrity"]["blocks"], blocks)

    def test_anchor_mismatch_aborts_without_output(self):
        dst = self.out("miss.asar")
        patch = {"id": "miss", "file": MAIN, "edits": [
            {"find": "this anchor does not exist in photon", "replace": "x", "count": 1}]}
        with self.assertRaises(asar.PatchError) as ctx:
            asar.apply(self.src, dst, [patch])
        self.assertIn("miss", str(ctx.exception))
        self.assertFalse(dst.exists())

    def test_check_reports_applied_state(self):
        dst = self.out("check.asar")
        patch = {"id": "c", "file": MAIN, "edits": [
            {"find": "// electron/feedback.ts", "replace": "// electron/feedback.ts /* chk */", "count": 1}]}
        self.assertEqual(asar.check(self.src, [patch]), {"c": False})
        asar.apply(self.src, dst, [patch])
        self.assertEqual(asar.check(dst, [patch]), {"c": True})

    def test_glob_file_resolves_to_the_one_file_with_the_anchor(self):
        dst = self.out("glob.asar")
        anchor = ".status-units .tz-select{width:88px}"
        patch = {"id": "g", "file": "dist/assets/index-*.css", "edits": [
            {"find": anchor, "replace": anchor + "/* glob */", "count": 1}]}
        asar.apply(self.src, dst, [patch])
        hits = [p for p, e in asar.entries(dst) if p.endswith(".css") and asar._packed(e)
                and "/* glob */" in asar.read_file(dst, p).decode("utf-8")]
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0].startswith("dist/assets/index-"))
        self.assertEqual(asar.check(dst, [patch]), {"g": True})
        self.assertEqual(asar.check(self.src, [patch]), {"g": False})

    def test_glob_file_must_match_exactly_one_file(self):
        for anchor in ("{", "no such anchor anywhere"):
            dst = self.out("globbad.asar")
            patch = {"id": "gb", "file": "dist/assets/index-*.css", "edits": [
                {"find": anchor, "replace": "x", "count": 1}]}
            with self.assertRaises(asar.PatchError) as ctx:
                asar.apply(self.src, dst, [patch])
            self.assertIn("gb", str(ctx.exception))
            self.assertFalse(dst.exists())

    def test_repo_patches_apply_to_stock(self):
        patches = [json.loads(p.read_text("utf-8")) for p in sorted((Path(__file__).resolve().parents[1] / "patches").glob("*.json"))]
        self.assertTrue(patches)
        dst = self.out("repo.asar")
        asar.apply(self.src, dst, patches)
        self.assertTrue(all(asar.check(dst, patches).values()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
