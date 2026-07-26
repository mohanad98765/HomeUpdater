"""The hub's TLS identity for agents — a self-signed certificate it owns.

Why self-signed and not a CA certificate: the hub is an app on someone's PC with no
public DNS name, so no CA can vouch for it. The agent does not need a CA to — it pins
this exact certificate at enrolment and refuses a different one afterwards, which is a
stronger statement than "some CA signed something for this name".

Consequences that are handled here rather than discovered later:

* the certificate names every address an agent might reach the hub on (hostname plus
  each local IP), because a pin is useless if the connection fails on the name;
* renewal is explicit: ``ensure_cert(force=True)`` writes a new one and the operator
  must re-enrol agents, since silently rotating would either break the fleet or make
  the pin meaningless — and this module refuses to hide that choice;
* the private key never enters the database or a log, and the files are written with
  an owner-only ACL on Windows.
"""

from __future__ import annotations

import datetime as dt
import getpass
import hashlib
import ipaddress
import socket
import subprocess
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from loguru import logger

from ..config import get_appdata_dir

CERT_NAME = "hub_tls_cert.pem"
KEY_NAME = "hub_tls_key.pem"
VALID_DAYS = 825  # the CA/Browser cap; long enough not to churn, short enough to age out


def cert_path() -> Path:
    return get_appdata_dir() / CERT_NAME


def key_path() -> Path:
    return get_appdata_dir() / KEY_NAME


def local_addresses() -> list[str]:
    """Every address an agent could plausibly use to reach this hub.

    Link-local addresses are dropped. An IPv6 ``fe80::`` literal is meaningless without
    a scope id, and the operator UI hands these to a human to type on another machine —
    offering an address that cannot work is worse than offering one fewer.
    """
    names = {socket.gethostname()}
    addresses = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            addr = info[4][0].split("%")[0]  # strip any scope id before parsing
            try:
                if ipaddress.ip_address(addr).is_link_local:
                    continue
            except ValueError:
                pass
            addresses.add(addr)
    except socket.gaierror:  # a machine with no resolvable name is still usable
        pass
    return sorted(names) + sorted(addresses)


def _san_entries() -> list[x509.GeneralName]:
    entries: list[x509.GeneralName] = []
    for value in local_addresses():
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(value)))
        except ValueError:
            entries.append(x509.DNSName(value))
    return entries


def _lock_down(path: Path) -> None:
    """Owner-only ACL. A private key readable by every local account is not private.

    The account running the app is granted too, not just Administrators and SYSTEM:
    the first version of this locked the app out of its own key, and regeneration —
    the one operation that has to work when a certificate expires — failed with
    PermissionError. A protection that blocks its own recovery path is a bug.
    """
    grants = ["*S-1-5-32-544:(F)", "*S-1-5-18:(F)"]  # Administrators, SYSTEM
    try:
        grants.append(f"{getpass.getuser()}:(F)")
    except Exception:  # noqa: BLE001 — no resolvable user name; the two SIDs suffice
        pass
    args = ["icacls", str(path), "/inheritance:r"]
    for grant in grants:
        args += ["/grant:r", grant]
    try:
        subprocess.run(args, check=False, capture_output=True, timeout=15)  # noqa: S603
    except Exception as exc:  # noqa: BLE001 — non-Windows or icacls missing
        logger.warning(f"could not restrict ACL on {path.name}: {exc}")


def fingerprint() -> str:
    """SHA-256 of the DER certificate — exactly what the agent pins."""
    file = cert_path()
    if not file.exists():
        return ""
    cert = x509.load_pem_x509_certificate(file.read_bytes())
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def ensure_cert(force: bool = False) -> dict:
    """Create the certificate if missing (or if ``force``). Returns its details."""
    cert_file, key_file = cert_path(), key_path()
    if cert_file.exists() and key_file.exists() and not force:
        cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
        expired = cert.not_valid_after_utc <= dt.datetime.now(dt.UTC)
        if not expired:
            return _describe(cert)
        logger.warning("hub TLS certificate expired — generating a new one")

    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    now = dt.datetime.now(dt.UTC)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, socket.gethostname()[:64] or "HomeUpdater"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "HomeUpdater Hub"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))  # tolerate a skewed client
        .not_valid_after(now + dt.timedelta(days=VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName(_san_entries()), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    cert_file.parent.mkdir(parents=True, exist_ok=True)
    # Remove first: the existing key is deliberately ACL-restricted, and overwriting a
    # restricted file is exactly the path that used to fail on renewal.
    for stale in (key_file, cert_file):
        try:
            stale.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError(f"cannot replace {stale.name}: {exc}") from exc
    key_file.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    _lock_down(key_file)
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    logger.info(f"hub TLS certificate generated: {fingerprint()[:16]}…")
    return _describe(cert)


def _describe(cert: x509.Certificate) -> dict:
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        names = [str(getattr(n, "value", n)) for n in san]
    except x509.ExtensionNotFound:
        names = []
    return {
        "fingerprint_sha256": hashlib.sha256(
            cert.public_bytes(serialization.Encoding.DER)
        ).hexdigest(),
        "not_before": cert.not_valid_before_utc.isoformat(),
        "not_after": cert.not_valid_after_utc.isoformat(),
        "names": names,
        "self_signed": True,
    }


def describe() -> dict:
    """Current certificate details, or ``{}`` when none exists yet."""
    file = cert_path()
    if not file.exists():
        return {}
    return _describe(x509.load_pem_x509_certificate(file.read_bytes()))
