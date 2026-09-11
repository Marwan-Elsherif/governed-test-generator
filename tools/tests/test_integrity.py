"""Tests for bundle integrity: sealing, tamper detection, and distribution.

The interesting cases are the adversarial ones. Hashes alone are easy to
defeat -- whoever edits a rule can refresh the manifest alongside it -- so
the tests below do exactly that, and assert what each layer does and does
not catch. That distinction is the whole point of the design, and stating
it in executable form keeps the claim honest.
"""
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import pytest

from govlib import integrity as I

ROOT = Path(__file__).resolve().parents[2]
signing = pytest.mark.skipif(not I.SIGNING_AVAILABLE,
                             reason="optional 'cryptography' package not installed")


def minimal_repo(root: Path, trusted: list[str] | None = None) -> Path:
    """A tree with just enough governance material to seal."""
    (root / "conventions").mkdir(parents=True, exist_ok=True)
    (root / "conventions" / "ui.md").write_text("- **UI-01 Title.** x\n", encoding="utf-8")
    (root / "conventions" / "api.md").write_text("- **API-01 Title.** x\n", encoding="utf-8")
    (root / "schemas").mkdir(exist_ok=True)
    (root / "schemas" / "audit.schema.json").write_text('{"type": "object"}\n', encoding="utf-8")
    (root / "tools" / "govlib").mkdir(parents=True, exist_ok=True)
    (root / "tools" / "gov.py").write_text("# cli\n", encoding="utf-8")
    (root / "tools" / "govlib" / "policy.py").write_text("# lib\n", encoding="utf-8")
    (root / "policy.json").write_text(
        json.dumps({"version": 1, "trusted_public_keys": trusted or []}, indent=2) + "\n",
        encoding="utf-8")
    return root


def key_at(path: Path) -> str:
    return I.generate_key(path)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def test_discover_finds_governance_files_and_ignores_everything_else(tmp_path):
    repo = minimal_repo(tmp_path)
    (repo / "features").mkdir()
    (repo / "features" / "x.feature").write_text("Feature: x\n", encoding="utf-8")
    (repo / "shop").mkdir()
    (repo / "shop" / "README.md").write_text("shop\n", encoding="utf-8")
    (repo / "tools" / "govlib" / "__pycache__").mkdir()
    (repo / "tools" / "govlib" / "__pycache__" / "policy.pyc").write_bytes(b"\x00")

    found = I.discover_files(repo)
    assert "conventions/ui.md" in found and "tools/govlib/policy.py" in found
    assert not any("features/" in f or "shop/" in f for f in found)
    assert not any("__pycache__" in f for f in found), "* must not span directories"


# ---------------------------------------------------------------------------
# Sealing and the four states
# ---------------------------------------------------------------------------

def test_no_manifest_is_not_configured(tmp_path):
    assert I.verify(minimal_repo(tmp_path)).state == I.STATE_NOT_CONFIGURED


def test_unsigned_seal_verifies_as_unsigned_never_ok(tmp_path):
    repo = minimal_repo(tmp_path)
    I.seal(repo, "1.0.0")
    result = I.verify(repo)
    assert result.state == I.STATE_UNSIGNED
    assert not result.ok
    assert any("no signature" in r for r in result.reasons)


def test_strict_treats_unsigned_as_tampered(tmp_path):
    repo = minimal_repo(tmp_path)
    I.seal(repo, "1.0.0")
    assert I.verify(repo, strict=True).state == I.STATE_TAMPERED


@signing
def test_signed_and_trusted_verifies_ok(tmp_path):
    repo = minimal_repo(tmp_path)
    key = tmp_path / "key.hex"
    public = key_at(key)
    I.seal(repo, "1.0.0", key_path=key, trust_this_key=True)
    result = I.verify(repo)
    assert result.ok and result.signed_by == public
    assert result.version == "1.0.0"


@signing
def test_signed_but_untrusted_is_unsigned_not_ok(tmp_path):
    """A valid signature by a key nobody vouched for proves the manifest is
    self-consistent, not that the publisher made it."""
    repo = minimal_repo(tmp_path)
    key = tmp_path / "key.hex"
    key_at(key)
    I.seal(repo, "1.0.0", key_path=key)  # no trust_this_key
    assert I.verify(repo).state == I.STATE_UNSIGNED


# ---------------------------------------------------------------------------
# Tamper detection
# ---------------------------------------------------------------------------

@signing
def test_modified_file_is_caught_and_named(tmp_path):
    repo = minimal_repo(tmp_path)
    key = tmp_path / "key.hex"
    key_at(key)
    I.seal(repo, "1.0.0", key_path=key, trust_this_key=True)

    (repo / "conventions" / "api.md").write_text("- **API-01 Title.** WEAKENED\n", encoding="utf-8")
    result = I.verify(repo)
    assert result.tampered
    assert result.modified == ("conventions/api.md",)
    assert any("conventions/api.md" in r for r in result.reasons)


@signing
def test_deleted_file_is_caught(tmp_path):
    repo = minimal_repo(tmp_path)
    key = tmp_path / "key.hex"
    key_at(key)
    I.seal(repo, "1.0.0", key_path=key, trust_this_key=True)
    (repo / "conventions" / "api.md").unlink()
    result = I.verify(repo)
    assert result.tampered and result.missing == ("conventions/api.md",)


@signing
def test_added_file_is_caught(tmp_path):
    """A rogue extra rule document must not slip in unnoticed just because
    the manifest says nothing about it."""
    repo = minimal_repo(tmp_path)
    key = tmp_path / "key.hex"
    key_at(key)
    I.seal(repo, "1.0.0", key_path=key, trust_this_key=True)
    (repo / "conventions" / "db.md").write_text("- **DB-01 X.** anything\n", encoding="utf-8")
    result = I.verify(repo)
    assert result.tampered and result.extra == ("conventions/db.md",)


def test_hashes_alone_do_not_stop_someone_who_reseals(tmp_path):
    """The honest limit of the hash-only mode, asserted rather than assumed:
    an editor who also refreshes the manifest passes. This is why `verify`
    reports `unsigned` instead of `ok`, why --strict exists for CI, and why
    the write-up does not claim hashes alone prevent tampering."""
    repo = minimal_repo(tmp_path)
    I.seal(repo, "1.0.0")
    (repo / "conventions" / "api.md").write_text("- **API-01 Title.** WEAKENED\n", encoding="utf-8")
    assert I.verify(repo).tampered

    I.seal(repo, "1.0.0")  # attacker refreshes the hashes
    assert I.verify(repo).state == I.STATE_UNSIGNED, "hash-only cannot catch this"
    assert I.verify(repo, strict=True).tampered, "strict mode refuses to accept it"


@signing
def test_resealing_with_a_different_key_is_caught(tmp_path):
    """The signed answer to the case above: re-sealing needs a key, and a
    different key is not the trusted one."""
    repo = minimal_repo(tmp_path)
    good, bad = tmp_path / "good.hex", tmp_path / "bad.hex"
    key_at(good)
    key_at(bad)
    I.seal(repo, "1.0.0", key_path=good, trust_this_key=True)

    (repo / "conventions" / "api.md").write_text("- **API-01 Title.** WEAKENED\n", encoding="utf-8")
    I.seal(repo, "1.0.0", key_path=bad)  # refresh hashes AND re-sign

    result = I.verify(repo)
    assert result.tampered
    assert any("not policy.json's trusted_public_keys" in r for r in result.reasons)


@signing
def test_edited_signature_value_is_caught(tmp_path):
    repo = minimal_repo(tmp_path)
    key = tmp_path / "key.hex"
    key_at(key)
    I.seal(repo, "1.0.0", key_path=key, trust_this_key=True)
    manifest = I.load_manifest(repo)
    manifest["version"] = "9.9.9"  # content changed, signature not refreshed
    I.save_manifest(repo, manifest)
    result = I.verify(repo)
    assert result.tampered
    assert any("signature does not match" in r for r in result.reasons)


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------

@signing
def test_bundle_and_install_into_a_fresh_repository(tmp_path):
    source = minimal_repo(tmp_path / "source")
    key = tmp_path / "key.hex"
    public = key_at(key)
    I.seal(source, "1.0.0", key_path=key, trust_this_key=True)

    archive = I.make_bundle(source, tmp_path / "dist")
    assert archive.exists()
    published = json.loads((tmp_path / "dist" / "LATEST.json").read_text())
    assert published["version"] == "1.0.0" and published["sha256"]

    target = tmp_path / "consumer"
    result = I.install(archive, target, trust_key=public)
    assert result.ok
    assert (target / "conventions" / "ui.md").exists()
    assert (target / I.MANIFEST_NAME).exists()
    # the consumer can verify on its own afterwards
    assert I.verify(target).ok
    # and notices its own local edit
    (target / "conventions" / "ui.md").write_text("- **UI-99 Anything.** goes\n", encoding="utf-8")
    assert I.verify(target).tampered


@signing
def test_install_refuses_a_bundle_signed_by_an_unexpected_key(tmp_path):
    source = minimal_repo(tmp_path / "source")
    key = tmp_path / "key.hex"
    key_at(key)
    I.seal(source, "1.0.0", key_path=key, trust_this_key=True)
    archive = I.make_bundle(source, tmp_path / "dist")

    target = tmp_path / "consumer"
    with pytest.raises(I.IntegrityError, match="not the key given"):
        I.install(archive, target, trust_key="00" * 32)
    assert not (target / "conventions").exists(), "nothing may be written on refusal"


def test_install_refuses_an_unsigned_bundle_unless_allowed(tmp_path):
    source = minimal_repo(tmp_path / "source")
    I.seal(source, "1.0.0")
    archive = I.make_bundle(source, tmp_path / "dist")

    with pytest.raises(I.IntegrityError, match="unsigned"):
        I.install(archive, tmp_path / "c1")
    result = I.install(archive, tmp_path / "c2", allow_untrusted=True)
    assert result.state == I.STATE_UNSIGNED
    assert (tmp_path / "c2" / "conventions" / "ui.md").exists()


def test_install_refuses_path_traversal_in_an_archive(tmp_path):
    evil = tmp_path / "evil.tar.gz"
    payload = tmp_path / "payload"
    payload.write_text("pwned\n", encoding="utf-8")
    with tarfile.open(evil, "w:gz") as tar:
        tar.add(payload, arcname="../../escaped.txt")
    with pytest.raises(I.IntegrityError, match="unsafe path"):
        I.install(evil, tmp_path / "target")


@signing
def test_bundle_refuses_to_publish_a_tampered_repository(tmp_path):
    source = minimal_repo(tmp_path / "source")
    key = tmp_path / "key.hex"
    key_at(key)
    I.seal(source, "1.0.0", key_path=key, trust_this_key=True)
    (source / "conventions" / "ui.md").write_text("- **UI-01 Title.** edited\n", encoding="utf-8")
    with pytest.raises(I.IntegrityError, match="fails verification"):
        I.make_bundle(source, tmp_path / "dist")


def test_update_check_compares_against_the_published_pointer(tmp_path):
    repo = minimal_repo(tmp_path)
    I.seal(repo, "1.0.0")
    latest = tmp_path / "LATEST.json"

    latest.write_text(json.dumps({"version": "1.0.0", "artifact": "a.tar.gz"}), encoding="utf-8")
    assert I.check_update(repo, latest)["up_to_date"] is True

    latest.write_text(json.dumps({"version": "1.1.0", "artifact": "b.tar.gz"}), encoding="utf-8")
    status = I.check_update(repo, latest)
    assert status["up_to_date"] is False
    assert status["local_version"] == "1.0.0" and status["published_version"] == "1.1.0"


# ---------------------------------------------------------------------------
# End to end through the real CLI
# ---------------------------------------------------------------------------

@signing
def test_declare_refuses_to_serve_conventions_when_a_rule_was_edited():
    """The demo in one test: weaken a convention after sealing, and the run
    cannot start. A fingerprint attesting to a locally edited rule would be
    worse than no fingerprint at all."""
    import simulate_run as S

    with tempfile.TemporaryDirectory(prefix="gov-integrity-cli-") as tmp:
        root = S.make_copy(Path(tmp) / "repo")
        key = Path(tmp) / "key.hex"
        public = I.generate_key(key)
        I.add_trusted_key(root, public)
        I.seal(root, "1.0.0", key_path=key)

        gov = [sys.executable, str(root / "tools" / "gov.py")]

        def cli(*args):
            return subprocess.run(gov + list(args), cwd=root, capture_output=True, text=True)

        assert cli("verify").returncode == 0

        api = root / "conventions" / "api.md"
        api.write_text(api.read_text(encoding="utf-8").replace(
            "- **API-06 Body assertion.**", "- **API-06 Body assertion (relaxed).**"),
            encoding="utf-8")

        verified = cli("verify")
        assert verified.returncode == 1 and "tampered" in verified.stdout

        declared = cli("declare", "--ticket", "TKT-2", "--domains", "api",
                       "--rationale", "r", "--evidence", "e")
        assert declared.returncode == 2, declared.stdout + declared.stderr
        assert "refusing to serve conventions" in declared.stderr
        assert "conventions/api.md" in declared.stderr
        assert not list((root / "runs").glob("*/served")), "nothing may be served"
