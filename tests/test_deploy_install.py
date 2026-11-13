"""deploy/install.sh: the release signing keys it trusts."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

INSTALL = Path(__file__).resolve().parent.parent / "deploy" / "install.sh"
_SIGNER = re.compile(r'[^\s]+ namespaces="git" ssh-(ed25519|rsa) [A-Za-z0-9+/]+=*')


def test_release_signers_lists_real_keys():
    match = re.search(r"^RELEASE_SIGNERS='([^']*)'$", INSTALL.read_text(), re.M)
    assert match, "RELEASE_SIGNERS='...' must stay a single-quoted line"
    keys = [line for line in match.group(1).splitlines() if line.strip()]
    assert keys, "list at least one release key"
    for key in keys:
        assert _SIGNER.fullmatch(key.strip()), f"not an allowed-signers line: {key[:40]}"


def _signers():
    match = re.search(r"^RELEASE_SIGNERS='([^']*)'$", INSTALL.read_text(), re.M)
    return [line.strip() for line in match.group(1).splitlines() if line.strip()]


@pytest.mark.skipif(not shutil.which("ssh-keygen"), reason="needs ssh-keygen")
def test_release_signers_are_valid_and_distinct(tmp_path):
    bodies = []
    for i, line in enumerate(_signers()):
        key_type, body = line.split(" namespaces=\"git\" ")[1].split()[:2]
        pub = tmp_path / f"k{i}.pub"
        pub.write_text(f"{key_type} {body}\n")
        run = subprocess.run(["ssh-keygen", "-l", "-f", str(pub)], capture_output=True)
        assert run.returncode == 0, f"ssh-keygen cannot read key {i + 1}"
        bodies.append(body)
    assert len(set(bodies)) == len(bodies), "a release key is listed twice"


@pytest.mark.skipif(
    not (shutil.which("ssh-keygen") and shutil.which("git")), reason="needs git and ssh-keygen"
)
def test_tag_signed_by_any_listed_key_verifies(tmp_path):
    """Same check as verify_release: a multi-line allowed-signers file, a tag signed by the 2nd key."""
    keys = []
    for name in ("first", "second"):
        path = tmp_path / name
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)], check=True)
        keys.append((path, path.with_suffix(".pub").read_text().split()[:2]))
    signers = tmp_path / "signers"
    signers.write_text(
        "".join(f'k{i} namespaces="git" {t} {b}\n' for i, (_, (t, b)) in enumerate(keys))
    )
    repo = tmp_path / "repo"
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    sign = ["-c", "gpg.format=ssh", "-c", f"user.signingkey={keys[1][0]}.pub"]
    subprocess.run([*git, *sign, "tag", "-s", "v9.9.9", "-m", "t"], check=True,
                   env={**os.environ, "SSH_AUTH_SOCK": ""})
    ok = subprocess.run([*git, "-c", f"gpg.ssh.allowedSignersFile={signers}", "verify-tag", "v9.9.9"],
                        capture_output=True)
    assert ok.returncode == 0, ok.stderr.decode()
