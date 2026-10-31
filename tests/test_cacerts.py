"""Unit tests for cacerts.py (system CA store lookup). No Qt, no network:
    python3 -m unittest discover -s tests -v
"""
import os
import shutil
import ssl
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cacerts  # noqa: E402

REAL = next((p for p in ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt",
                         "/etc/ssl/cert.pem") if os.path.isfile(p)), None)


@unittest.skipIf(REAL is None, "no CA bundle on this machine to use as test data")
class CAStoreTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        # all known locations are re-rooted into the temp dir; nothing exists by default
        self.files = tuple(self.root + p for p in cacerts.CA_FILES)
        self.dirs = tuple(self.root + p for p in cacerts.CA_DIRS)
        for target, new in ((cacerts, "CA_FILES"), (cacerts, "CA_DIRS")):
            p = mock.patch.object(target, new, self.files if new == "CA_FILES" else self.dirs)
            p.start(); self.addCleanup(p.stop)
        dv = ssl.DefaultVerifyPaths(None, None, "", "", "", "")
        p = mock.patch.object(ssl, "get_default_verify_paths", return_value=dv)
        p.start(); self.addCleanup(p.stop)

    def put(self, path, src=REAL):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if src is None:
            open(path, "w").close()
        elif isinstance(src, str) and os.path.isfile(src):
            shutil.copy(src, path)
        else:
            with open(path, "w") as f:
                f.write(src)
        return path

    def find(self, env=None):
        return cacerts.find_ca_store(env or {}, use_cache=False)

    def test_fedora_layout(self):
        """Bazzite / Fedora: only /etc/pki exists, no /etc/ssl/certs."""
        f = self.put(self.root + "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem")
        self.assertEqual(self.find(), ("cafile", f, "system"))
        f2 = self.put(self.root + "/etc/pki/tls/certs/ca-bundle.crt")
        self.assertEqual(self.find(), ("cafile", f2, "system"))      # first in the order wins

    def test_debian_and_opensuse(self):
        f = self.put(self.root + "/var/lib/ca-certificates/ca-bundle.pem")
        self.assertEqual(self.find()[1], f)
        f = self.put(self.root + "/etc/ssl/certs/ca-certificates.crt")
        self.assertEqual(self.find()[1], f)

    def test_env_wins_and_bad_env_is_skipped(self):
        sysf = self.put(self.root + "/etc/ssl/cert.pem")
        own = self.put(self.root + "/own/bundle.pem")
        self.assertEqual(self.find({"SSL_CERT_FILE": own}), ("cafile", own, "SSL_CERT_FILE"))
        self.assertEqual(self.find({"SSL_CERT_FILE": self.root + "/missing.pem"})[1], sysf)

    def test_hashed_dir(self):
        d = self.root + "/etc/ssl/certs"
        self.put(d + "/1a2b3c4d.0")
        self.assertEqual(self.find(), ("capath", d, "system"))
        d2 = self.root + "/envdir"
        self.put(d2 + "/deadbeef.0")
        self.assertEqual(self.find({"SSL_CERT_DIR": d2}), ("capath", d2, "SSL_CERT_DIR"))

    def test_dir_without_hashed_certs_ignored(self):
        self.put(self.root + "/etc/ssl/certs/README", "x")
        self.assertIsNone(self.find())

    def test_empty_or_garbage_bundle_ignored(self):
        self.put(self.root + "/etc/pki/tls/certs/ca-bundle.crt", None)
        self.put(self.root + "/etc/ssl/cert.pem", "not a certificate\n")
        good = self.put(self.root + "/etc/ssl/ca-bundle.pem")
        self.assertEqual(self.find()[1], good)

    def test_context_always_verifies(self):
        self.put(self.root + "/etc/pki/tls/certs/ca-bundle.crt")
        ctx = cacerts.https_context({}, use_cache=False)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        self.assertGreater(ctx.cert_store_stats()["x509_ca"], 0)

    def test_no_store_raises_and_names_paths(self):
        with self.assertRaises(cacerts.NoCAStoreError) as cm:
            cacerts.https_context({}, use_cache=False)
        msg = str(cm.exception)
        self.assertIn("/etc/pki/tls/certs/ca-bundle.crt", msg)
        self.assertIn("SSL_CERT_FILE", msg)


class CertProblemTests(unittest.TestCase):
    def test_classification(self):
        v = ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
        self.assertTrue(cacerts.is_cert_problem(urllib.error.URLError(v)))
        self.assertTrue(cacerts.is_cert_problem(cacerts.NoCAStoreError("x")))
        self.assertFalse(cacerts.is_cert_problem(urllib.error.URLError(OSError(-3, "Temporary failure in name resolution"))))
        self.assertFalse(cacerts.is_cert_problem(TimeoutError("timed out")))


if __name__ == "__main__":
    unittest.main()
