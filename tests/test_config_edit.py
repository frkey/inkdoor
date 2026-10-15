import hashlib
import os
import stat
import subprocess
import sys
import threading

import pytest

from inkdoor import config, config_edit
from inkdoor.config_edit import ConfigChanged, RawConfig, check, read_raw, restore_backup, save
from inkdoor.files import write_private

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")


def test_save_round_trips_without_adding_defaults(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[display]\nlanguage = "pt-BR"\nfoo = 1\n[[calendar]]\nname = "Empresa \\"Ltda\\" & Cia 🎯"\n'
                 'url = "https://x/a?b=1&c=2"\n', encoding="utf-8")
    raw = read_raw(p)
    raw.data["display"]["timezone"] = "America/Sao_Paulo"
    save(p, raw.data, raw.digest)
    again = read_raw(p).data
    assert again["display"] == {"language": "pt-BR", "foo": 1, "timezone": "America/Sao_Paulo"}
    assert again["calendar"][0]["name"] == 'Empresa "Ltda" & Cia 🎯'
    assert again["calendar"][0]["url"] == "https://x/a?b=1&c=2"
    assert "server" not in again                        # defaults not pinned


def test_language_override_is_never_written(tmp_path, monkeypatch):
    monkeypatch.setenv("INKDOOR_LANG", "pt-BR")
    p = tmp_path / "config.toml"
    p.write_text('[display]\nlanguage = "en-US"\n')
    raw = read_raw(p)
    save(p, raw.data, raw.digest)
    assert read_raw(p).data == {"display": {"language": "en-US"}}


@posix_only
def test_files_are_private_under_umask_022(tmp_path):
    old = os.umask(0o022)
    try:
        p = tmp_path / "config.toml"
        p.write_text("")
        raw = read_raw(p)
        save(p, {"display": {"language": "en-US"}}, raw.digest)
    finally:
        os.umask(old)
    for name in ["config.toml", "config.toml.bak"]:
        assert stat.S_IMODE(os.stat(tmp_path / name).st_mode) == 0o600
    assert not (tmp_path / "config.toml.tmp").exists()


def test_save_returns_the_new_digest_and_keeps_the_previous_bytes(tmp_path):
    p = tmp_path / "config.toml"
    p.write_bytes(b"# hand-written comment\n[server]\nport = 8001\n")
    raw = read_raw(p)
    assert raw.exists and raw.digest == hashlib.sha256(p.read_bytes()).hexdigest()
    digest = save(p, {"server": {"port": 8002}}, raw.digest)
    assert digest == hashlib.sha256(p.read_bytes()).hexdigest() == read_raw(p).digest
    assert (tmp_path / "config.toml.bak").read_bytes() == b"# hand-written comment\n[server]\nport = 8001\n"


def test_concurrent_change_is_refused(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[server]\nport = 8001\n")
    raw = read_raw(p)
    p.write_text("[server]\nport = 8003\n")             # hand edit in between
    with pytest.raises(ConfigChanged):
        save(p, {"server": {"port": 8002}}, raw.digest)
    assert p.read_text() == "[server]\nport = 8003\n"
    assert not (tmp_path / "config.toml.bak").exists()


def test_restore_backup(tmp_path):
    p = tmp_path / "config.toml"
    raw = read_raw(p)
    first = save(p, {"server": {"port": 8001}}, raw.digest)
    first_bytes = p.read_bytes()
    second = save(p, {"server": {"port": 8002}}, first)
    restored = restore_backup(p, second)
    assert p.read_bytes() == first_bytes
    assert restored == first
    assert read_raw(p).data == {"server": {"port": 8001}}
    # The version that was replaced becomes the backup, so the restore can be undone.
    assert read_raw(tmp_path / "config.toml.bak").data == {"server": {"port": 8002}}


def test_restore_backup_rescues_a_broken_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[server]\nport = 8001\n")
    raw = read_raw(p)
    save(p, {"server": {"port": 8002}}, raw.digest)
    p.write_text("[server\n")                          # broken by hand
    with pytest.raises(config.ConfigInvalid):
        read_raw(p)
    current = hashlib.sha256(p.read_bytes()).hexdigest()
    restore_backup(p, current)
    assert p.read_text() == "[server]\nport = 8001\n"
    assert (tmp_path / "config.toml.bak").read_text() == "[server\n"


def test_restore_backup_refuses_a_bad_or_stale_backup(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[server]\nport = 8001\n")
    digest = read_raw(p).digest
    (tmp_path / "config.toml.bak").write_text("[server]\nport = 70000\n")
    with pytest.raises(config.ConfigInvalid) as err:
        restore_backup(p, digest)
    assert err.value.key == "port"
    (tmp_path / "config.toml.bak").write_text("[server\n")
    with pytest.raises(config.ConfigInvalid) as err:
        restore_backup(p, digest)
    assert err.value.key == "syntax"
    (tmp_path / "config.toml.bak").write_text("[server]\nport = 8002\n")
    with pytest.raises(ConfigChanged):
        restore_backup(p, EMPTY_DIGEST)
    assert p.read_text() == "[server]\nport = 8001\n"


def test_restore_keeps_the_good_bytes_if_the_backup_write_fails(tmp_path, monkeypatch):
    p = tmp_path / "config.toml"
    p.write_text("[server]\nport = 8001\n")
    save(p, {"server": {"port": 8002}}, read_raw(p).digest)
    good = (tmp_path / "config.toml.bak").read_bytes()
    p.write_text("[server\n")                          # broken by hand
    real = config_edit.write_private

    def fail_on_backup(path, data):
        if os.fspath(path).endswith(".bak"):
            raise OSError("disk full")
        real(path, data)

    monkeypatch.setattr(config_edit, "write_private", fail_on_backup)
    with pytest.raises(OSError):
        restore_backup(p, hashlib.sha256(p.read_bytes()).hexdigest())
    assert p.read_bytes() == good
    assert (tmp_path / "config.toml.bak").read_bytes() == good


@pytest.mark.parametrize("bad", [None, "", "é" * 64, "A" * 64, 3, "0" * 63, "0" * 65],
                         ids=["none", "empty", "non-ascii", "uppercase", "int", "short", "long"])
def test_malformed_digest_is_a_change_not_a_crash(tmp_path, bad):
    p = tmp_path / "config.toml"
    p.write_text("[server]\nport = 8001\n")
    with pytest.raises(ConfigChanged):
        save(p, {"server": {"port": 8002}}, bad)
    with pytest.raises(ConfigChanged):
        save(tmp_path / "missing.toml", {"server": {"port": 8002}}, bad)
    assert p.read_text() == "[server]\nport = 8001\n"


def test_uppercase_digest_is_refused(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[server]\nport = 8001\n")
    with pytest.raises(ConfigChanged):
        save(p, {"server": {"port": 8002}}, read_raw(p).digest.upper())


@pytest.mark.parametrize("existing", [True, False])
def test_concurrent_saves_with_the_same_digest_let_exactly_one_win(tmp_path, existing):
    for run in range(25):
        p = tmp_path / f"config{run}.toml"
        if existing:
            p.write_text("[server]\nport = 8001\n")
        expected = read_raw(p).digest
        barrier = threading.Barrier(2)
        results = []

        def worker(port):
            barrier.wait()
            try:
                save(p, {"server": {"port": port}}, expected)
                results.append("ok")
            except ConfigChanged:
                results.append("changed")
            except Exception as ex:                     # pragma: no cover - the failure we guard against
                results.append(repr(ex))

        threads = [threading.Thread(target=worker, args=(port,)) for port in (8002, 8003)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(results) == ["changed", "ok"]
        assert read_raw(p).data["server"]["port"] in (8002, 8003)
        assert not (tmp_path / f"config{run}.toml.tmp").exists()


def test_write_private_leaves_another_writers_tmp_alone_when_it_cannot_open(tmp_path, monkeypatch):
    p = tmp_path / "config.toml"
    tmp = tmp_path / "config.toml.tmp"
    real_open = os.open

    def racing_open(path, flags, mode=0o777):
        tmp.write_text("another writer")                # someone created it after the stale cleanup
        return real_open(path, flags, mode)

    monkeypatch.setattr(os, "open", racing_open)
    with pytest.raises(FileExistsError):
        write_private(p, b"data")
    assert tmp.read_text() == "another writer"


def test_restore_without_backup_is_a_config_error(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[server]\nport = 8001\n")
    with pytest.raises(config.ConfigInvalid):
        restore_backup(p, read_raw(p).digest)


def test_missing_file_reads_empty_and_first_save_creates_it(tmp_path):
    p = tmp_path / "config.toml"
    raw = read_raw(p)
    assert raw == RawConfig({}, EMPTY_DIGEST, False)
    raw.data.setdefault("display", {})["language"] = "pt-BR"
    save(p, raw.data, raw.digest)
    assert read_raw(str(p)).data == {"display": {"language": "pt-BR"}}
    assert read_raw(p).exists
    assert not (tmp_path / "config.toml.bak").exists()


def test_missing_file_refuses_a_save_once_someone_created_it(tmp_path):
    p = tmp_path / "config.toml"
    raw = read_raw(p)
    p.write_text("[server]\nport = 8001\n")
    with pytest.raises(ConfigChanged):
        save(p, {"display": {"language": "pt-BR"}}, raw.digest)


def test_check_rejects_bad_values():
    with pytest.raises(config.ConfigInvalid) as err:
        check({"display": {"workday_start": "8"}})
    assert err.value.key == "hour"
    with pytest.raises(config.ConfigInvalid) as err:
        check({"display": 3})
    assert err.value.key == "section"


def test_check_validates_a_copy():
    data = {"display": {"language": "pt-BR"}}
    checked = check(data)
    assert checked["server"]["port"] == 8000
    assert data == {"display": {"language": "pt-BR"}}


def test_save_validates_before_writing(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[server]\nport = 8001\n")
    raw = read_raw(p)
    with pytest.raises(config.ConfigInvalid) as err:
        save(p, {"server": {"port": 0}}, raw.digest)
    assert err.value.key == "port"
    assert p.read_text() == "[server]\nport = 8001\n"
    assert not (tmp_path / "config.toml.bak").exists()


def test_admin_section_defaults_and_validation():
    cfg = check({})
    assert cfg["admin"] == {"enabled": False, "allowed_hosts": []}
    assert check({"admin": {"enabled": True, "allowed_hosts": ["door.example"]}})["admin"]["enabled"] is True
    for admin, key in [({"enabled": "yes"}, "admin_enabled"), ({"enabled": 1}, "admin_enabled"),
                       ({"allowed_hosts": "door.example"}, "allowed_hosts"),
                       ({"allowed_hosts": ["door.example", ""]}, "allowed_hosts"),
                       ({"allowed_hosts": [3]}, "allowed_hosts")]:
        with pytest.raises(config.ConfigInvalid) as err:
            check({"admin": admin})
        assert err.value.key == key
    with pytest.raises(config.ConfigInvalid) as err:
        check({"admin": True})
    assert err.value.key == "section"


def test_defaults_are_not_shared_between_configs():
    one = config.with_defaults({})
    one["admin"]["allowed_hosts"].append("door.example")
    assert config.with_defaults({})["admin"]["allowed_hosts"] == []
    assert config.ADMIN_DEFAULTS == {"enabled": False, "allowed_hosts": []}


@posix_only
def test_permission_error_is_a_config_error(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root can read any file")
    p = tmp_path / "config.toml"
    p.write_text("[server]\nport = 8001\n")
    p.chmod(0)
    try:
        for read in (config.load, read_raw):
            with pytest.raises(config.ConfigInvalid) as err:
                read(str(p))
            assert err.value.key == "permission"
            assert err.value.details == {"path": str(p)}
    finally:
        p.chmod(0o600)


def test_unreadable_file_is_a_config_error(tmp_path):
    p = tmp_path / "config.toml"
    p.mkdir()                                           # a directory cannot be read as a file
    for read in (config.load, read_raw):
        with pytest.raises(config.ConfigInvalid) as err:
            read(str(p))
        assert err.value.key == "unreadable"
        assert err.value.details["error"] in ("IsADirectoryError", "PermissionError")


@posix_only
def test_write_private_replaces_a_stale_tmp_and_keeps_mode_600(tmp_path):
    p = tmp_path / "admin-password"
    (tmp_path / "admin-password.tmp").write_text("stale")
    old = os.umask(0o022)
    try:
        write_private(p, b"line\r\nsecond\n")
        write_private(str(p), b"new\n")
    finally:
        os.umask(old)
    assert p.read_bytes() == b"new\n"
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert not (tmp_path / "admin-password.tmp").exists()


def test_write_private_removes_the_tmp_on_failure(tmp_path):
    target = tmp_path / "config.toml"
    target.mkdir()
    (target / "keep").write_text("x")                   # os.replace onto a non-empty dir fails
    with pytest.raises(OSError):
        write_private(target, b"data")
    assert not (tmp_path / "config.toml.tmp").exists()


def test_resolve_path(monkeypatch):
    monkeypatch.delenv("INKDOOR_CONFIG", raising=False)
    assert config.resolve_path(None) == "config.toml"
    monkeypatch.setenv("INKDOOR_CONFIG", "/etc/inkdoor/config.toml")
    assert config.resolve_path(None) == "/etc/inkdoor/config.toml"
    assert config.resolve_path("mine.toml") == "mine.toml"


def test_gitignore_covers_secrets():
    out = subprocess.run(["git", "check-ignore", "config.toml.bak", "config.toml.tmp", "admin-password"],
                         capture_output=True, text=True, cwd=REPO_ROOT)
    assert out.stdout.split() == ["config.toml.bak", "config.toml.tmp", "admin-password"]
