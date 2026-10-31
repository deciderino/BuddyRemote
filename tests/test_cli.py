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


# --- 1.3.1: custom CLI, Buddy API mismatch, CLI update check ---------------------------
GOOD_CLI = """#!/bin/sh
if [ "$1" = "--help" ]; then echo "usage: moondeck-cli [-h] ..."; exit 0; fi
printf '%s\\n' "$@" > "$0.args"
echo custom
"""
BAD_CLI = """#!/bin/sh
echo "Segmentation fault" >&2
exit 139
"""


@unittest.skipUnless(HAVE_QT and sys.platform.startswith("linux"), "PyQt6 / Linux only")
class CustomCliTests(unittest.TestCase):
    setUp = CliResolutionTests.setUp            # same temp copy / packaged helpers
    tearDown = CliResolutionTests.tearDown
    packaged = CliResolutionTests.packaged
    fake_cli = CliResolutionTests.fake_cli

    def script(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(0o755)
        return path

    def setup_pkg(self):
        self.fake_cli(self.bundle / "bundled" / "moondeck-cli")
        a = self.packaged()
        a.prepare_packaged_dir()
        self.events = []
        a.set_cli_listener(lambda *ev: self.events.append(ev))
        self.addCleanup(a.set_cli_listener, None)
        self.addCleanup(a.set_custom_cli, "")
        return a

    def test_default_is_bundled(self):
        a = self.setup_pkg()
        self.assertEqual(a.active_cli(), a.CLI_BIN)
        self.assertEqual(a.custom_cli_state()[0], "off")
        self.assertEqual(a.run_cli(["x"], timeout=10)[1].strip(), '{"ok": true}')

    def test_custom_used_when_it_starts(self):
        a = self.setup_pkg()
        good = self.script(self.tmp / "my" / "moondeck-cli", GOOD_CLI)
        a.set_custom_cli(str(good))
        self.assertEqual(a.active_cli(), good)
        self.assertEqual(a.custom_cli_state()[0], "ok")
        rc, out, _ = a.run_cli(["host", "list"], timeout=10)
        self.assertEqual((rc, out.strip()), (0, "custom"))
        self.assertEqual(self.events, [("ok", str(good), "")])
        a.active_cli()
        self.assertEqual(len(self.events), 1, "probed once per file version")

    def test_custom_that_does_not_start_falls_back(self):
        a = self.setup_pkg()
        bad = self.script(self.tmp / "my" / "bad-cli", BAD_CLI)
        a.set_custom_cli(str(bad))
        rc, out, _ = a.run_cli(["host", "list"], timeout=10)
        self.assertEqual(out.strip(), '{"ok": true}', "bundled CLI ran")
        state, reason = a.custom_cli_state()
        self.assertEqual(state, "failed")
        self.assertIn("139", reason)
        self.assertEqual([e[0] for e in self.events], ["failed"])
        self.assertEqual(a.custom_cli_path(), str(bad), "the setting is kept")
        a.run_cli(["host", "list"], timeout=10)
        self.assertEqual(len(self.events), 1, "no repeated warning")
        # fixed file (new mtime/size) -> probed again and used
        self.script(bad, GOOD_CLI)
        os.utime(bad, ns=(1, 2))
        self.assertEqual(a.active_cli(), bad)
        self.assertEqual(self.events[-1][0], "ok")

    def test_not_executable_falls_back(self):
        a = self.setup_pkg()
        f = self.tmp / "my" / "plain.txt"
        f.parent.mkdir(parents=True)
        f.write_text("not a program")
        a.set_custom_cli(str(f))
        rc, out, _ = a.run_cli(["x"], timeout=10)
        self.assertEqual(out.strip(), '{"ok": true}')
        self.assertEqual(a.custom_cli_state()[0], "failed")

    def test_missing_file_falls_back_and_keeps_setting(self):
        a = self.setup_pkg()
        good = self.script(self.tmp / "my" / "moondeck-cli", GOOD_CLI)
        a.set_custom_cli(str(good))
        self.assertEqual(a.active_cli(), good)
        good.unlink()
        rc, out, _ = a.run_cli(["x"], timeout=10)
        self.assertEqual(out.strip(), '{"ok": true}')
        self.assertEqual(a.custom_cli_state()[0], "missing")
        self.assertEqual(a.custom_cli_path(), str(good))
        self.assertEqual([e[0] for e in self.events], ["ok", "missing"])
        self.script(good, GOOD_CLI)          # back again
        self.assertEqual(a.active_cli(), good)

    def test_start_error_after_probe_reruns_bundled(self):
        a = self.setup_pkg()
        good = self.script(self.tmp / "my" / "moondeck-cli", GOOD_CLI)
        a.set_custom_cli(str(good))
        self.assertEqual(a.active_cli(), good)
        real = a._exec_cli
        calls = []

        def flaky(cli, *rest):
            calls.append(cli)
            if cli == good:
                raise PermissionError(13, "Permission denied")
            return real(cli, *rest)
        a._exec_cli = flaky                  # AppView: lands in backend, where run_cli looks
        try:
            rc, out, _ = a.run_cli(["x"], timeout=10)
        finally:
            a._exec_cli = real
        self.assertEqual(calls, [good, a.CLI_BIN])
        self.assertEqual(out.strip(), '{"ok": true}')
        self.assertEqual(a.custom_cli_state()[0], "failed")

    def test_cli_available_with_custom_only(self):
        a = self.packaged()                 # nothing bundled
        a.prepare_packaged_dir()
        self.addCleanup(a.set_custom_cli, "")
        self.assertFalse(a.cli_available())
        good = self.script(self.tmp / "my" / "moondeck-cli", GOOD_CLI)
        a.set_custom_cli(str(good))
        self.assertTrue(a.cli_available())
        self.assertEqual(a.run_cli(["x"], timeout=10)[1].strip(), "custom")

    def test_source_mode_custom(self):
        a = load_app("br_cli_src_custom", self.src)
        self.addCleanup(a.set_custom_cli, "")
        self.fake_cli(self.src / "cli" / "moondeck-cli")
        bad = self.script(self.tmp / "my" / "bad", BAD_CLI)
        a.set_custom_cli(str(bad))
        self.assertEqual(a.run_cli(["x"], timeout=10)[1].strip(), '{"ok": true}')
        good = self.script(self.tmp / "my" / "good", GOOD_CLI)
        a.set_custom_cli(str(good))
        self.assertEqual(a.run_cli(["x"], timeout=10)[1].strip(), "custom")

    def test_probe(self):
        a = load_app("br_cli_probe", self.src)
        self.assertEqual(a.probe_cli(self.script(self.tmp / "g", GOOD_CLI)), (True, ""))
        ok, why = a.probe_cli(self.tmp / "nope")
        self.assertFalse(ok)
        self.assertTrue(why)
        ok, why = a.probe_cli(self.fake_cli(self.tmp / "nousage"))
        self.assertFalse(ok, "exit 0 without argparse usage is no MoonDeck CLI")

    def test_config_default_and_sanitize(self):
        a = load_app("br_cli_cfg", self.src)
        self.assertEqual(a.DEFAULT_CONFIG["settings"]["custom_cli"], "")
        data = {"hosts": [], "settings": {"custom_cli": 5}}
        a.sanitize_config(data)
        self.assertEqual(data["settings"]["custom_cli"], "")
        data = {"hosts": [], "settings": {"custom_cli": "/opt/md/cli"}}
        a.sanitize_config(data)
        self.assertEqual(data["settings"]["custom_cli"], "/opt/md/cli")

    # --- Buddy API -------------------------------------------------------------
    def test_parse_api_version(self):
        a = load_app("br_api", self.src)
        self.assertEqual(a.parse_api_version('{"version": 9}'), 9)
        self.assertEqual(a.parse_api_version('{"version": "8"}'), 8)
        for bad in ("", "nope", "[]", '{"version": true}', '{"version": "x"}', '{}', None):
            self.assertIsNone(a.parse_api_version(bad), bad)

    def test_api_mismatch_both_directions(self):
        a = load_app("br_api2", self.src)
        self.assertIsNone(a.api_mismatch(9, want=9))
        self.assertEqual(a.api_mismatch(8, want=9), {"host": 8, "want": 9, "dir": "host_old"})
        self.assertEqual(a.api_mismatch(10, want=9), {"host": 10, "want": 9, "dir": "host_new"})
        self.assertIsNone(a.api_mismatch(None, "all fine", want=9))
        self.assertEqual(a.api_mismatch(None, "x MoonDeck/Buddy needs update! y", want=9)["dir"],
                         "unknown")
        self.assertIsNone(a.api_mismatch(9, "MoonDeck/Buddy needs update!", want=9),
                          "a known matching version wins")

    def test_expected_api_from_bundle(self):
        a = self.packaged()
        self.assertEqual(a.expected_buddy_api(), 9, "default")
        (self.bundle / "bundled" / "moondeck-cli.version").write_text(
            json.dumps({"version": "nightly", "commit": "00f8c31", "sha256": "ab", "buddy_api": 10}))
        self.assertEqual(a.expected_buddy_api(), 10)
        self.assertEqual(a.api_mismatch(9)["dir"], "host_old")
        self.assertEqual(a.bundled_cli_label(), "nightly 00f8c31")

    # --- CLI update check ------------------------------------------------------------
    REL = {"html_url": "https://github.com/FrogTheFrog/moondeck/releases/tag/nightly",
           "target_commitish": "4b1e9d2aa0000000000000000000000000000000",
           "published_at": "2026-01-01T00:00:00Z",
           "assets": [{"name": "moondeck-cli-linux.bin", "digest": "sha256:" + "ab" * 32},
                      {"name": "moondeck-cli-win.exe", "digest": "sha256:" + "cd" * 32}]}

    def test_parse_cli_release(self):
        a = load_app("br_rel", self.src)
        r = a.parse_cli_release(self.REL, "moondeck-cli-linux.bin")
        self.assertEqual((r["digest"], r["commit"]), ("ab" * 32, "4b1e9d2"))
        self.assertEqual(a.parse_cli_release(self.REL, "moondeck-cli-win.exe")["digest"], "cd" * 32)
        self.assertEqual(a.cli_asset_name("win32"), "moondeck-cli-win.exe")
        self.assertEqual(a.cli_asset_name("linux"), "moondeck-cli-linux.bin")
        r = a.parse_cli_release({"target_commitish": "main", "html_url": "http://evil.example"},
                                "moondeck-cli-linux.bin")
        self.assertEqual((r["digest"], r["commit"], r["url"]), ("", "", a.CLI_RELEASE_PAGE))

    def test_compare_cli_release(self):
        a = load_app("br_rel2", self.src)
        rel = a.parse_cli_release(self.REL, "moondeck-cli-linux.bin")
        same = a.compare_cli_release("AB" * 32, rel)
        self.assertEqual((same["ok"], same["newer"]), (True, False))
        other = a.compare_cli_release("ef" * 32, rel)
        self.assertEqual((other["ok"], other["newer"], other["commit"]), (True, True, "4b1e9d2"))
        self.assertFalse(a.compare_cli_release("", rel)["ok"])
        self.assertFalse(a.compare_cli_release("ab" * 32, {"digest": ""})["ok"])

    def test_bundled_digest_ignores_custom(self):
        cli = self.fake_cli(self.bundle / "bundled" / "moondeck-cli")
        a = self.packaged()
        self.addCleanup(a.set_custom_cli, "")
        (self.bundle / "bundled" / "moondeck-cli.version").write_text(
            json.dumps({"version": "nightly", "commit": "00f8c31", "sha256": "12" * 32}))
        a.set_custom_cli(str(self.script(self.tmp / "my" / "c", GOOD_CLI)))
        self.assertEqual(a.bundled_cli_digest(), "12" * 32, "packaged: pinned digest")
        (self.bundle / "bundled" / "moondeck-cli.version").unlink()
        self.assertEqual(a.bundled_cli_digest(), a.sha256_file(cli))
