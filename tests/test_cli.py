"""MoonDeck CLI resolution (1.3.1): packaged builds run the CLI straight from the
bundle with cwd = the user dir and the user's LD_LIBRARY_PATH; source mode uses
APP_DIR/cli. Loads app.py twice (source / simulated packaged). Skipped without PyQt6.
    QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_cli -v
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HAVE_QT = importlib.util.find_spec("PyQt6") is not None

FAKE_CLI = """#!/bin/sh
printf '%s\\n' "$@" > "$0.args"
pwd > "$0.cwd"
printf '%s' "${LD_LIBRARY_PATH-<unset>}" > "$0.ld"
echo '{"ok": true}'
"""


# app.py was split into modules (1.3.1); each load must import them from the copy, fresh.
SPLIT_MODULES = ("paths", "i18n", "config", "backend", "platform_util", "theme", "gamepad", "dialogs")


def purge_split_modules():
    for m in SPLIT_MODULES:
        sys.modules.pop(m, None)


class AppView:
    """app.py plus the modules split out of it: reads look in app first, then in the split
    modules; writes (stubs) go to app and to every split module that has the name."""
    def __init__(self, mod):
        object.__setattr__(self, "_mods", [mod] + [sys.modules[m] for m in SPLIT_MODULES
                                                   if m in sys.modules])

    def __getattr__(self, name):
        for m in self._mods:
            if hasattr(m, name):
                return getattr(m, name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        for i, m in enumerate(self._mods):
            if i == 0 or hasattr(m, name):
                setattr(m, name, value)


def load_app(name, src_dir, packaged_env=None, meipass=None):
    """Import a copy of app.py (and its split modules, from the same copy);
    packaged_env/meipass simulate the AppImage."""
    saved_env = dict(os.environ)
    had = hasattr(sys, "_MEIPASS")
    old_mei = getattr(sys, "_MEIPASS", None)
    try:
        os.environ.pop("APPIMAGE", None)
        os.environ.update(packaged_env or {})
        if meipass:
            sys._MEIPASS = str(meipass)
        spec = importlib.util.spec_from_file_location(name, src_dir / "app.py")
        mod = importlib.util.module_from_spec(spec)
        purge_split_modules()
        sys.path.insert(0, str(src_dir))
        try:
            spec.loader.exec_module(mod)
            return AppView(mod)
        finally:
            sys.path.remove(str(src_dir))
            purge_split_modules()
    finally:
        os.environ.clear()
        os.environ.update(saved_env)
        if had:
            sys._MEIPASS = old_mei
        elif hasattr(sys, "_MEIPASS"):
            del sys._MEIPASS


@unittest.skipUnless(HAVE_QT and sys.platform.startswith("linux"), "PyQt6 / Linux only")
class CliResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="br-cli-"))
        self.src = self.tmp / "src"
        self.src.mkdir()
        for f in ROOT.glob("*.py"):
            shutil.copy(f, self.src / f.name)
        shutil.copytree(ROOT / "lang", self.src / "lang")
        self.bundle = self.tmp / "bundle"                  # fake _MEIPASS
        (self.bundle / "bundled").mkdir(parents=True)
        self.cfg_home = self.tmp / "xdg"
        sys.path.insert(0, str(self.src))

    def tearDown(self):
        sys.path.remove(str(self.src))
        shutil.rmtree(self.tmp, ignore_errors=True)

    def packaged(self):
        return load_app("br_cli_pkg", self.src, {"APPIMAGE": str(self.tmp / "BR.AppImage"),
                                                 "XDG_CONFIG_HOME": str(self.cfg_home)},
                        meipass=self.bundle)

    def fake_cli(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(FAKE_CLI)
        path.chmod(0o755)
        return path

    # --- path resolution ------------------------------------------------------
    def test_source_mode_uses_app_dir_cli(self):
        a = load_app("br_cli_src", self.src)
        self.assertFalse(a.PACKAGED)
        self.assertEqual(a.CLI_BIN, self.src / "cli" / "moondeck-cli")
        self.assertEqual(a.cli_path(False), self.src / "cli" / "moondeck-cli")
        self.assertEqual(a.cli_path(True), self.src / "bundled" / "moondeck-cli")

    def test_packaged_uses_bundle_directly(self):
        a = self.packaged()
        self.assertTrue(a.PACKAGED)
        self.assertEqual(a.APP_DIR, self.cfg_home / "BuddyRemote")
        self.assertEqual(a.CLI_BIN, self.bundle / "bundled" / "moondeck-cli")
        self.assertFalse(a.cli_available(), "nothing bundled yet")
        self.fake_cli(self.bundle / "bundled" / "moondeck-cli")
        self.assertTrue(a.cli_available())

    def test_old_user_copy_ignored_and_untouched(self):
        old_dir = self.cfg_home / "BuddyRemote" / "cli"
        old_bin = self.fake_cli(old_dir / "moondeck-cli")
        (old_dir / "moondeck-cli.version").write_text('{"version": "old"}')
        before = {p.name: p.read_bytes() for p in old_dir.iterdir()}
        a = self.packaged()
        a.prepare_packaged_dir()
        self.assertFalse(a.cli_available(), "1.3 copy in the user dir is not used")
        self.assertIsNone(a.bundled_cli_info(), "version only from the bundle")
        (self.bundle / "bundled" / "moondeck-cli.version").write_text(
            json.dumps({"version": "nightly", "commit": "00f8c31", "sha256": "ab"}))
        self.assertEqual(a.bundled_cli_info()["version"], "nightly")
        self.assertEqual({p.name: p.read_bytes() for p in old_dir.iterdir()}, before)
        self.assertTrue(old_bin.exists())

    def test_prepare_packaged_dir_copies_nothing(self):
        self.fake_cli(self.bundle / "bundled" / "moondeck-cli")
        a = self.packaged()
        a.prepare_packaged_dir()
        self.assertTrue(a.APP_DIR.is_dir())
        self.assertFalse((a.APP_DIR / "cli").exists())

    # --- environment ----------------------------------------------------------
    def test_child_env(self):
        a = load_app("br_cli_env", self.src)
        base = {"LD_LIBRARY_PATH": "/bundle", "LD_LIBRARY_PATH_ORIG": "/usr/local/lib", "X": "1"}
        self.assertEqual(a.child_env(True, base)["LD_LIBRARY_PATH"], "/usr/local/lib")
        e = a.child_env(True, {"LD_LIBRARY_PATH": "/bundle", "X": "1"})
        self.assertNotIn("LD_LIBRARY_PATH", e)
        self.assertEqual(e["X"], "1")
        self.assertEqual(a.child_env(False, base), base, "source mode: unchanged")
        self.assertIsNot(a.child_env(False, base), base, "always a copy")

    # --- run_cli invocation -----------------------------------------------------
    def check_run(self, a, cli, expect_ld):
        rc, out, err = a.run_cli(["host", "list", "--json"], timeout=10)
        self.assertEqual((rc, out.strip()), (0, '{"ok": true}'), err)
        args = Path(str(cli) + ".args").read_text().splitlines()
        self.assertEqual(args, ["--config-file", str(a.CONFIG_FILE), "host", "list", "--json"])
        self.assertEqual(Path(Path(str(cli) + ".cwd").read_text().strip()).resolve(),
                         a.APP_DIR.resolve())
        self.assertEqual(Path(str(cli) + ".ld").read_text(), expect_ld)
        override = self.tmp / ".pair_x.json"
        a.run_cli(["steam", "status"], timeout=10, config_override=override)
        args = Path(str(cli) + ".args").read_text().splitlines()
        self.assertEqual(args, ["--config-file", str(override), "steam", "status"])

    def test_run_cli_packaged(self):
        cli = self.fake_cli(self.bundle / "bundled" / "moondeck-cli")
        a = self.packaged()
        a.prepare_packaged_dir()
        saved = dict(os.environ)
        try:
            os.environ["LD_LIBRARY_PATH"] = str(self.bundle)
            os.environ["LD_LIBRARY_PATH_ORIG"] = "/opt/userlib"
            self.check_run(a, cli, "/opt/userlib")
            del os.environ["LD_LIBRARY_PATH_ORIG"]
            self.check_run(a, cli, "<unset>")
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_run_cli_source(self):
        a = load_app("br_cli_src2", self.src)
        cli = self.fake_cli(self.src / "cli" / "moondeck-cli")
        saved = dict(os.environ)
        try:
            os.environ["LD_LIBRARY_PATH"] = "/kept"
            self.check_run(a, cli, "/kept")
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_missing_cli(self):
        a = self.packaged()
        rc, out, err = a.run_cli(["host", "list"])
        self.assertEqual((rc, out), (-1, ""))
        self.assertTrue(err)


if __name__ == "__main__":
    unittest.main()
