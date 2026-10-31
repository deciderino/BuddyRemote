"""System CA certificate store lookup for HTTPS to GitHub (update check, CLI checksum).

No CA list is bundled. The AppImage carries its own OpenSSL, which only looks at the
build distro's default path (Debian: /usr/lib/ssl -> /etc/ssl/certs). On Fedora,
Bazzite, RHEL, openSUSE etc. that path does not exist, so verification failed with
"certificate verify failed: unable to get local issuer certificate". Here the system
store is searched explicitly; certificate verification always stays on.

No Qt here (unit tested in tests/test_cacerts.py)."""
import os
import re
import ssl

# Bundle files, in this order (first existing, loadable one wins).
CA_FILES = (
    "/etc/pki/tls/certs/ca-bundle.crt",                    # Fedora, Bazzite, RHEL, CentOS
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",   # Fedora, RHEL (p11-kit extract)
    "/etc/ssl/certs/ca-certificates.crt",                  # Debian, Ubuntu, Arch, SteamOS, Alpine
    "/etc/ssl/cert.pem",                                   # Arch, Alpine, macOS-style
    "/etc/ssl/ca-bundle.pem",                              # openSUSE
    "/var/lib/ca-certificates/ca-bundle.pem",              # openSUSE
)
# Directories with OpenSSL hashed certificates (c_rehash: 1a2b3c4d.0).
CA_DIRS = (
    "/etc/ssl/certs",                                      # Alpine, Debian, most others
    "/etc/pki/tls/certs",
    "/var/lib/ca-certificates/openssl",                    # openSUSE
)
_HASHED = re.compile(r"^[0-9a-f]{8}\.\d+$")


class NoCAStoreError(ssl.SSLError):
    """No usable system CA store (verification is never switched off instead)."""


def _file_ok(path: str) -> bool:
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0 and os.access(path, os.R_OK)
    except OSError:
        return False


def _dir_ok(path: str) -> bool:
    try:
        return os.path.isdir(path) and any(_HASHED.match(n) for n in os.listdir(path))
    except OSError:
        return False


def _loads(kind: str, path: str) -> bool:
    """The candidate really contains certificates OpenSSL can use."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        ctx.load_verify_locations(**{kind: path})
    except (ssl.SSLError, OSError, ValueError):
        return False
    return kind == "capath" or ctx.cert_store_stats().get("x509_ca", 0) > 0


def candidates(env=None):
    """(kind, path, source) in search order; kind is "cafile" or "capath"."""
    env = os.environ if env is None else env
    out = []
    if env.get("SSL_CERT_FILE"):
        out.append(("cafile", env["SSL_CERT_FILE"], "SSL_CERT_FILE"))
    for d in (env.get("SSL_CERT_DIR") or "").split(os.pathsep):
        if d:
            out.append(("capath", d, "SSL_CERT_DIR"))
    out += [("cafile", p, "system") for p in CA_FILES]
    out += [("capath", p, "system") for p in CA_DIRS]
    try:                                   # what the (bundled) OpenSSL itself would use
        dv = ssl.get_default_verify_paths()
        if dv.cafile:
            out.append(("cafile", dv.cafile, "openssl default"))
        if dv.capath:
            out.append(("capath", dv.capath, "openssl default"))
    except Exception:
        pass
    return out


_cache = {}


def find_ca_store(env=None, use_cache=True):
    """First usable (kind, path, source), or None. Skipped candidates are reported in
    the NoCAStoreError message by https_context()."""
    key = None
    if use_cache and env is None:
        key = (os.environ.get("SSL_CERT_FILE"), os.environ.get("SSL_CERT_DIR"))
        if key in _cache:
            return _cache[key]
    found = None
    for kind, path, source in candidates(env):
        ok = _file_ok(path) if kind == "cafile" else _dir_ok(path)
        if ok and _loads(kind, path):
            found = (kind, path, source)
            break
    if key is not None:
        _cache[key] = found
    return found


def https_context(env=None, use_cache=True) -> ssl.SSLContext:
    """Verifying TLS client context with the system CA store (hostname check + CERT_REQUIRED,
    as ssl.create_default_context()). Raises NoCAStoreError if none is found."""
    found = find_ca_store(env, use_cache)
    if found is None:
        checked = ", ".join(p for _, p, _ in candidates(env))
        raise NoCAStoreError("no system CA certificate store found (checked: %s). "
                             "Install ca-certificates or set SSL_CERT_FILE." % checked)
    kind, path, _ = found
    ctx = ssl.create_default_context(**{kind: path})
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    return ctx


def describe(env=None) -> str:
    found = find_ca_store(env)
    return "none" if found is None else "%s (%s)" % (found[1], found[2])


def is_cert_problem(exc) -> bool:
    """True for certificate / TLS trust errors (also wrapped in urllib's URLError)."""
    e = getattr(exc, "reason", exc)
    return isinstance(e, (ssl.SSLCertVerificationError, NoCAStoreError)) or \
        isinstance(exc, (ssl.SSLCertVerificationError, NoCAStoreError)) or \
        "CERTIFICATE_VERIFY_FAILED" in str(exc)
