"""Windows port (1.4): platform switches that can be checked on any OS (paths, version
comparison of the preview, update asset, child env, autostart command, CA store choice).
Skipped without PyQt6 (backend imports i18n -> Qt).
    QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_windows -v
"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path, PureWindowsPath
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
HAVE_QT = importlib.util.find_spec("PyQt6") is not None

import cacerts  # noqa: E402
import paths  # noqa: E402


class PathTests(unittest.TestCase):
    def test_user_data_dir_windows(self):
        d = paths.user_data_dir("win32", {"APPDATA": r"C:\Users\Example\AppData\Roaming"}, Path("/h"))
        self.assertEqual(PureWindowsPath(str(d).replace("/", "\\")),
                         PureWindowsPath(r"C:\Users\Example\AppData\Roaming\BuddyRemote"))
        d = paths.user_data_dir("win32", {}, Path("/h"))
        self.assertEqual(d, Path("/h") / "AppData" / "Roaming" / "BuddyRemote", "no APPDATA: default location")

    def test_user_data_dir_linux_unchanged(self):
        self.assertEqual(paths.user_data_dir("linux", {}, Path("/h")), Path("/h/.config/BuddyRemote"))
        self.assertEqual(paths.user_data_dir("linux", {"XDG_CONFIG_HOME": "/x"}, Path("/h")),
                         Path("/x/BuddyRemote"))
        self.assertEqual(paths.user_data_dir("linux", {"APPDATA": "/a"}, Path("/h")),
                         Path("/h/.config/BuddyRemote"), "APPDATA is ignored on Linux")

    def test_cli_name(self):
        self.assertEqual(paths.cli_name("win32"), "moondeck-cli.exe")
        self.assertEqual(paths.cli_name("linux"), "moondeck-cli")
        self.assertEqual(paths.cli_path(True, "win32"), paths.BUNDLED_DIR / "moondeck-cli.exe")
        self.assertEqual(paths.cli_path(False, "win32"), paths.CLI_DIR / "moondeck-cli.exe")
        self.assertEqual(paths.cli_path(True, "linux"), paths.BUNDLED_DIR / "moondeck-cli")


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class BackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # private copy: other test modules stub functions (e.g. ping_icmp) on the shared
        # backend module in sys.modules
        spec = importlib.util.spec_from_file_location(
            "backend_windows_test", os.path.join(os.path.dirname(__file__), "..", "backend.py"))
        cls.b = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.b)

    def test_preview_version(self):
        b = self.b
        self.assertTrue(b.is_prerelease("1.4-preview"))
        self.assertTrue(b.is_prerelease("v1.4rc1"))
        self.assertFalse(b.is_prerelease("1.4"))
        self.assertFalse(b.is_prerelease("v1.4.0"))
        self.assertFalse(b.is_newer_version("1.3.1", "1.4-preview"), "no 'update' to 1.3.1")
        self.assertFalse(b.is_newer_version("1.4-preview", "1.4-preview"))
        self.assertTrue(b.is_newer_version("1.4", "1.4-preview"), "final release replaces the preview")
        self.assertTrue(b.is_newer_version("v1.4.0", "1.4-preview"))
        self.assertTrue(b.is_newer_version("1.4.1", "1.4-preview"))
        self.assertFalse(b.is_newer_version("1.4-preview", "1.4"), "a preview is never newer than its final")
        self.assertFalse(b.is_newer_version("1.4-beta", "1.4-preview"), "equal numbers, both pre-releases")
        # unchanged 1.3.1 behaviour
        self.assertTrue(b.is_newer_version("1.3.2", "1.3.1"))
        self.assertFalse(b.is_newer_version("1.3.1", "1.3.1"))
        self.assertFalse(b.is_newer_version("1.3", "1.3.0"))
        self.assertFalse(b.is_newer_version("", "1.3.1"))

    def test_release_asset(self):
        b = self.b
        self.assertEqual(b.release_asset_name("win32"), "BuddyRemote-Windows-x86_64.zip")
        self.assertEqual(b.release_asset_name("linux"), "BuddyRemote-x86_64.AppImage")
        rel = {"version": "9.9", "has_asset": False}
        self.assertFalse(b.release_is_update(rel, "win32"), "Windows: release without the Windows zip")
        self.assertTrue(b.release_is_update(rel, "linux"), "Linux: unchanged (version only)")
        self.assertTrue(b.release_is_update({"version": "9.9", "has_asset": True}, "win32"))
        self.assertFalse(b.release_is_update({"version": "1.3.1", "has_asset": True}, "win32"))

    def test_fetch_latest_release_has_asset(self):
        b = self.b
        import io
        import json

        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        data = {"tag_name": "1.4", "html_url": "https://github.com/x/y/releases/tag/1.4",
                "assets": [{"name": b.release_asset_name()}]}
        with mock.patch.object(b.urllib.request, "urlopen", lambda *a, **k: R(json.dumps(data).encode())):
            self.assertTrue(b.fetch_latest_release()["has_asset"])
            data["assets"] = []
            self.assertFalse(b.fetch_latest_release()["has_asset"])

    def test_child_env_windows(self):
        b = self.b
        base = {"PATH": r"C:\Windows", "LD_LIBRARY_PATH": "x"}
        e = b.child_env(True, base, "win32")
        self.assertEqual(e["PATH"], r"C:\Windows")
        self.assertEqual(e["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertEqual(b.child_env(False, base, "win32"), base, "source mode: unchanged")
        self.assertNotIn("PYINSTALLER_RESET_ENVIRONMENT", b.child_env(True, base, "linux"))

    def test_no_window_flag(self):
        b = self.b
        with mock.patch.object(b.sys, "platform", "win32"):
            self.assertEqual(b._no_window(), {"creationflags": 0x08000000})
        with mock.patch.object(b.sys, "platform", "linux"):
            self.assertEqual(b._no_window(), {})

    def test_ping_windows_flags(self):
        b = self.b
        seen = {}

        class P:
            returncode = 0
            stdout = "Antwort von 192.0.2.20: Bytes=32 Zeit<1ms TTL=128"

        def fake_run(cmd, **kw):
            seen["cmd"], seen["kw"] = cmd, kw
            return P()
        with mock.patch.object(b.sys, "platform", "win32"), mock.patch.object(b.subprocess, "run", fake_run):
            self.assertTrue(b.ping_icmp("192.0.2.20", 1))
            self.assertEqual(seen["cmd"], ["ping", "-n", "1", "-w", "1000", "192.0.2.20"])
            self.assertEqual(seen["kw"].get("creationflags"), 0x08000000)
            P.stdout = "Antwort von 192.0.2.1: Zielhost nicht erreichbar."
            self.assertFalse(b.ping_icmp("192.0.2.20", 1), "exit 0 without TTL= is not a reply")


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class AutostartTests(unittest.TestCase):
    def test_command_windows(self):
        import platform_util as pu
        with mock.patch.object(pu.sys, "executable", r"C:\Apps\BuddyRemote\BuddyRemote.exe"):
            self.assertEqual(pu.autostart_command(True, "win32"), r'"C:\Apps\BuddyRemote\BuddyRemote.exe"')
        cmd = pu.autostart_command(False, "win32")
        self.assertTrue(cmd.endswith('app.py"') and cmd.startswith('"'), cmd)

    def test_command_linux_unchanged(self):
        import platform_util as pu
        with mock.patch.dict(os.environ, {"APPIMAGE": "/opt/BuddyRemote-x86_64.AppImage"}):
            self.assertEqual(pu.autostart_command(True, "linux"), "/opt/BuddyRemote-x86_64.AppImage")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("APPIMAGE", None)
            self.assertEqual(pu.autostart_command(False, "linux"), str(pu.APP_DIR / "BuddyRemote"))


class CAStoreWindowsTests(unittest.TestCase):
    def test_windows_store(self):
        self.assertEqual(cacerts.find_ca_store({}, False, "win32"), cacerts.WINDOWS_STORE)
        ctx = cacerts.https_context({}, False, "win32")
        self.assertTrue(ctx.check_hostname)

    def test_env_override_wins(self):
        found = cacerts.find_ca_store({"SSL_CERT_FILE": "/nonexistent.pem"}, False, "win32")
        self.assertNotEqual(found, cacerts.WINDOWS_STORE)


if __name__ == "__main__":
    unittest.main()
