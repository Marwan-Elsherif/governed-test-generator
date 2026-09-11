"""Bundle integrity: what counts as governance material, whether it still
matches what was published, and how it travels to another repository.

The honest threat model, stated up front because it decides the design:

  The manifest lives inside the repository it protects. Anyone who can
  edit `conventions/api.md` can also edit `MANIFEST.json` to match. Hashes
  alone therefore catch accidental drift, a half-finished edit, a bad
  merge -- not a determined actor. What a determined actor cannot do is
  re-sign the manifest, because the private key is not in the repository.
  So the signature is what makes tampering *detectable*; the hashes are
  what make it *cheap to check*.

  Even signed, local verification can be subverted by editing the verifier
  (this file is itself in the bundle, and the code checking the hash is the
  code you just edited). That is not a flaw to be engineered around
  locally: the real control is CI running `verify` from a trusted checkout
  against a known public key, plus CODEOWNERS on governance paths. Local
  verification is fast feedback; CI is the boundary. This mirrors the
  hook-versus-git split elsewhere in this tool: preventive where it is
  convenient, detective where it has to be trustworthy.

Signing uses Ed25519 via `cryptography`, which is an *optional* dependency.
`gov.py` is otherwise stdlib-only so it can be vendored into another team's
repository without an install step, and integrity checking must not be the
thing that breaks that. Without the package, hashes are still checked and
the state is reported as `unsigned` -- never as `ok`, because an unverified
signature is not a verified one.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from govlib.policy import glob_to_regex

try:  # optional: signing and signature verification
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey,
    )
    SIGNING_AVAILABLE = True
except ImportError:  # hashes still work; see module docstring
    SIGNING_AVAILABLE = False

MANIFEST_NAME = "MANIFEST.json"
MANIFEST_SCHEMA = "gov-manifest/1"
DEFAULT_BUNDLE = "governed-test-generation"
DEFAULT_KEY_PATH = Path.home() / ".governed-test-gen" / "signing_key.hex"

# What travels between repositories: the rules, the policy, the tooling that
# enforces them, and the Copilot wiring that invokes it. Deliberately not the
# shop specification, tickets, features or runs -- those belong to the
# consuming repository, not to the governance bundle.
BUNDLE_GLOBS = (
    "conventions/*.md",
    "policy.json",
    "schemas/*.json",
    "tools/gov.py",
    "tools/govlib/*.py",
    ".github/agents/*.agent.md",
    ".github/prompts/*.prompt.md",
    ".github/hooks/*.json",
    ".github/copilot-instructions.md",
    ".vscode/settings.json",
)

STATE_OK = "ok"
STATE_TAMPERED = "tampered"
STATE_UNSIGNED = "unsigned"
STATE_NOT_CONFIGURED = "not_configured"


class IntegrityError(RuntimeError):
    """Sealing or installing could not proceed."""


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Discovery and hashing
# ---------------------------------------------------------------------------

def discover_files(repo_root: Path, globs=BUNDLE_GLOBS) -> list[str]:
    """Every governance file present on disk, repository-relative, sorted.

    Walks the tree rather than using Path.glob per pattern so that a file
    *added* under a bundle path is discovered too -- `verify` has to notice
    a rogue `conventions/ui.md.bak` or a fourth domain appearing, not only
    changes to files the manifest already knows about.
    """
    patterns = [glob_to_regex(g) for g in globs]
    found: list[str] = []
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        if any(p.match(rel) for p in patterns):
            found.append(rel)
    return found


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hash_files(repo_root: Path, rel_paths) -> dict[str, str]:
    return {rel: hash_file(repo_root / rel) for rel in rel_paths}


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def manifest_path(repo_root: Path) -> Path:
    return repo_root / MANIFEST_NAME


def build_manifest(repo_root: Path, version: str, bundle: str = DEFAULT_BUNDLE) -> dict:
    files = discover_files(repo_root)
    if not files:
        raise IntegrityError(f"{repo_root}: no governance files found to seal")
    return {
        "schema": MANIFEST_SCHEMA,
        "bundle": bundle,
        "version": version,
        "created_at": utcnow(),
        "algorithm": "sha256",
        "globs": list(BUNDLE_GLOBS),
        "files": hash_files(repo_root, files),
    }


def canonical_bytes(manifest: dict) -> bytes:
    """Exactly what gets signed: the manifest without its own signature,
    serialised deterministically so the same content always produces the
    same bytes on any machine."""
    payload = {k: v for k, v in manifest.items() if k != "signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_manifest(repo_root: Path) -> dict | None:
    path = manifest_path(repo_root)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise IntegrityError(f"{path}: not valid JSON ({exc})") from exc


def save_manifest(repo_root: Path, manifest: dict) -> Path:
    path = manifest_path(repo_root)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Keys and signing
# ---------------------------------------------------------------------------

def generate_key(key_path: Path = DEFAULT_KEY_PATH) -> str:
    """Create a signing key outside the repository. Returns the public key
    as hex, which is what a consuming repository trusts."""
    if not SIGNING_AVAILABLE:
        raise IntegrityError(
            "signing needs the optional 'cryptography' package: pip install cryptography"
        )
    if key_path.exists():
        raise IntegrityError(f"{key_path} already exists; refusing to overwrite a signing key")
    key_path.parent.mkdir(parents=True, exist_ok=True)
    private = Ed25519PrivateKey.generate()
    raw = private.private_bytes_raw().hex()
    key_path.write_text(raw + "\n", encoding="utf-8")
    os.chmod(key_path, 0o600)
    return public_key_hex(key_path)


def load_private_key(key_path: Path = DEFAULT_KEY_PATH):
    if not SIGNING_AVAILABLE:
        raise IntegrityError("signing needs the optional 'cryptography' package")
    if not key_path.exists():
        raise IntegrityError(f"no signing key at {key_path}; run `gov.py keygen` first")
    return Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(key_path.read_text(encoding="utf-8").strip())
    )


def public_key_hex(key_path: Path = DEFAULT_KEY_PATH) -> str:
    return load_private_key(key_path).public_key().public_bytes_raw().hex()


def sign_manifest(manifest: dict, key_path: Path = DEFAULT_KEY_PATH) -> dict:
    private = load_private_key(key_path)
    signed = {k: v for k, v in manifest.items() if k != "signature"}
    signed["signature"] = {
        "algorithm": "ed25519",
        "public_key": private.public_key().public_bytes_raw().hex(),
        "value": private.sign(canonical_bytes(signed)).hex(),
        "signed_at": utcnow(),
    }
    return signed


def signature_is_valid(manifest: dict) -> bool:
    sig = manifest.get("signature") or {}
    if not SIGNING_AVAILABLE or not sig.get("value") or not sig.get("public_key"):
        return False
    try:
        public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(sig["public_key"]))
        public.verify(bytes.fromhex(sig["value"]), canonical_bytes(manifest))
        return True
    except (InvalidSignature, ValueError):
        return False


def trusted_keys(repo_root: Path) -> tuple[str, ...]:
    """Public keys this repository accepts, from policy.json.

    The trust anchor deliberately lives in policy.json, which the manifest
    itself covers: editing the trusted key list changes policy.json's hash,
    so a swapped key is caught unless the attacker can also re-sign. The
    bootstrap case (how a fresh repository learns the first key) is not
    solvable in-band and is not pretended to be -- it comes from the
    platform team's own channel, or `install --trust-key`.
    """
    try:
        data = json.loads((repo_root / "policy.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    return tuple(data.get("trusted_public_keys") or ())


def add_trusted_key(repo_root: Path, public_key: str) -> None:
    path = repo_root / "policy.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    keys = list(data.get("trusted_public_keys") or ())
    if public_key not in keys:
        keys.append(public_key)
    data["trusted_public_keys"] = keys
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VerifyResult:
    state: str
    version: str | None = None
    bundle: str | None = None
    modified: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()
    signed_by: str | None = None
    reasons: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.state == STATE_OK

    @property
    def tampered(self) -> bool:
        return self.state == STATE_TAMPERED

    def summary(self) -> str:
        if self.state == STATE_NOT_CONFIGURED:
            return "not_configured: no MANIFEST.json; nothing to verify"
        head = f"{self.state}: {self.bundle} {self.version}"
        if self.signed_by:
            head += f" signed by {self.signed_by[:16]}..."
        return head

    def as_dict(self) -> dict:
        return {
            "state": self.state, "version": self.version, "bundle": self.bundle,
            "modified": list(self.modified), "missing": list(self.missing),
            "extra": list(self.extra), "signed_by": self.signed_by,
            "reasons": list(self.reasons),
        }


def verify(repo_root: Path, *, strict: bool = False,
           trusted_override: tuple[str, ...] | None = None) -> VerifyResult:
    """Compare what is on disk against the manifest, and check the manifest
    is signed by a key this repository trusts.

    `strict` refuses to accept `unsigned` as tolerable: use it in CI, where
    an unsigned manifest means anyone who edited a rule could have refreshed
    the hashes alongside it.

    `trusted_override` names the keys to accept instead of the ones in the
    checked-out policy.json. `install` uses it to check a freshly unpacked
    bundle against a key the installer already knew, without writing that
    key into the staged files first -- doing so would change policy.json's
    hash and break the very manifest being verified.
    """
    manifest = load_manifest(repo_root)
    if manifest is None:
        return VerifyResult(STATE_NOT_CONFIGURED)

    recorded: dict[str, str] = manifest.get("files") or {}
    globs = tuple(manifest.get("globs") or BUNDLE_GLOBS)
    on_disk = set(discover_files(repo_root, globs))

    modified, missing = [], []
    for rel, expected in sorted(recorded.items()):
        path = repo_root / rel
        if not path.exists():
            missing.append(rel)
        elif hash_file(path) != expected:
            modified.append(rel)
    extra = sorted(on_disk - set(recorded))

    reasons: list[str] = []
    for rel in modified:
        reasons.append(f"modified since it was sealed: {rel}")
    for rel in missing:
        reasons.append(f"in the manifest but missing from disk: {rel}")
    for rel in extra:
        reasons.append(f"present on disk but not in the manifest: {rel}")

    version, bundle = manifest.get("version"), manifest.get("bundle")
    sig = manifest.get("signature") or {}
    signed_by = sig.get("public_key")

    if modified or missing or extra:
        return VerifyResult(STATE_TAMPERED, version, bundle, tuple(modified),
                            tuple(missing), tuple(extra), signed_by, tuple(reasons))

    if not sig:
        reasons.append("the manifest carries no signature, so its hashes could have been "
                       "refreshed by whoever changed the files")
        state = STATE_TAMPERED if strict else STATE_UNSIGNED
        return VerifyResult(state, version, bundle, signed_by=None, reasons=tuple(reasons))

    if not SIGNING_AVAILABLE:
        reasons.append("the manifest is signed but the optional 'cryptography' package is "
                       "not installed, so the signature could not be checked")
        state = STATE_TAMPERED if strict else STATE_UNSIGNED
        return VerifyResult(state, version, bundle, signed_by=signed_by, reasons=tuple(reasons))

    if not signature_is_valid(manifest):
        reasons.append("the signature does not match the manifest contents")
        return VerifyResult(STATE_TAMPERED, version, bundle, signed_by=signed_by,
                            reasons=tuple(reasons))

    trusted = trusted_override if trusted_override is not None else trusted_keys(repo_root)
    if trusted and signed_by not in trusted:
        where = ("the key given on the command line" if trusted_override is not None
                 else "policy.json's trusted_public_keys")
        reasons.append(f"signed by {signed_by[:16]}..., which is not {where}")
        return VerifyResult(STATE_TAMPERED, version, bundle, signed_by=signed_by,
                            reasons=tuple(reasons))
    if not trusted:
        reasons.append("no trusted public key is configured, so the signature proves only "
                       "internal consistency, not who produced it")
        state = STATE_TAMPERED if strict else STATE_UNSIGNED
        return VerifyResult(state, version, bundle, signed_by=signed_by, reasons=tuple(reasons))

    return VerifyResult(STATE_OK, version, bundle, signed_by=signed_by,
                        reasons=("hashes match and the signature is by a trusted key",))


def seal(repo_root: Path, version: str, *, key_path: Path | None = None,
         bundle: str = DEFAULT_BUNDLE, trust_this_key: bool = False) -> dict:
    manifest = build_manifest(repo_root, version, bundle)
    if key_path is not None:
        if trust_this_key:
            add_trusted_key(repo_root, public_key_hex(key_path))
            # policy.json just changed, so its hash has to be recomputed.
            manifest = build_manifest(repo_root, version, bundle)
        manifest = sign_manifest(manifest, key_path)
    save_manifest(repo_root, manifest)
    return manifest


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------

def bundle_name(manifest: dict) -> str:
    return f"{manifest.get('bundle', DEFAULT_BUNDLE)}-{manifest.get('version', '0')}.tar.gz"


def make_bundle(repo_root: Path, out_dir: Path) -> Path:
    """Package the sealed governance material for distribution."""
    manifest = load_manifest(repo_root)
    if manifest is None:
        raise IntegrityError("nothing to bundle: run `gov.py seal` first")
    result = verify(repo_root)
    if result.tampered:
        raise IntegrityError("refusing to bundle a repository that fails verification: "
                             + "; ".join(result.reasons))
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / bundle_name(manifest)
    with tarfile.open(out, "w:gz") as tar:
        for rel in sorted(manifest["files"]):
            tar.add(repo_root / rel, arcname=rel)
        tar.add(manifest_path(repo_root), arcname=MANIFEST_NAME)
    (out_dir / "LATEST.json").write_text(
        json.dumps({
            "bundle": manifest.get("bundle"), "version": manifest.get("version"),
            "artifact": out.name, "sha256": hash_file(out), "published_at": utcnow(),
        }, indent=2) + "\n", encoding="utf-8")
    return out


def install(archive: Path, target: Path, *, trust_key: str | None = None,
            allow_untrusted: bool = False) -> VerifyResult:
    """Unpack a bundle into another repository, verifying before anything is
    written. Only governance files move; the target's own shop, tickets,
    features and run records are never touched."""
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gov-install-") as tmp:
        staging = Path(tmp)
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                name = Path(member.name)
                if member.issym() or member.islnk() or name.is_absolute() or ".." in name.parts:
                    raise IntegrityError(f"refusing unsafe path in bundle: {member.name}")
            tar.extractall(staging)

        # Verify exactly what was published, unmodified. The trusted key is
        # supplied as an override rather than written into the staged files:
        # policy.json is covered by the manifest, so editing it here would
        # invalidate the hash this check depends on. Precedence: a key named
        # on the command line, else the target repository's existing trust
        # list, else whatever the bundle itself carries (trust on first use,
        # which is reported as `unsigned` unless explicitly allowed).
        if trust_key:
            override: tuple[str, ...] | None = (trust_key,)
        elif (target / "policy.json").exists() and trusted_keys(target):
            override = trusted_keys(target)
        else:
            override = None

        staged = verify(staging, trusted_override=override)
        if staged.tampered:
            raise IntegrityError("bundle failed verification, nothing installed: "
                                 + "; ".join(staged.reasons))
        if staged.state == STATE_UNSIGNED and not allow_untrusted:
            raise IntegrityError(
                "bundle is unsigned, or no trusted key was given to check it against, so "
                "nothing was installed: " + "; ".join(staged.reasons)
                + " -- pass --trust-key <hex> to name the key you expect (obtain it from the "
                "publishing team, not from the bundle), or --allow-untrusted to accept it "
                "on faith")

        manifest = load_manifest(staging) or {}
        for rel in sorted(manifest.get("files", {})):
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(staging / rel, dest)
        shutil.copyfile(manifest_path(staging), manifest_path(target))
    return verify(target)


def check_update(repo_root: Path, latest: Path) -> dict:
    """Compare the installed bundle against a published pointer. Minimal on
    purpose: in a real deployment this is an HTTPS GET against an artifact
    registry, not a file read."""
    manifest = load_manifest(repo_root)
    local_version = (manifest or {}).get("version")
    try:
        published = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise IntegrityError(f"cannot read {latest}: {exc}") from exc
    return {
        "local_version": local_version,
        "published_version": published.get("version"),
        "artifact": published.get("artifact"),
        "up_to_date": local_version == published.get("version"),
    }
