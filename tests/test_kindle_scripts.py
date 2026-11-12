"""The Kindle's shell helpers (kindle/inkdoor/common.sh), run with sh on this computer."""
import os
import subprocess

import pytest

FOLDER = os.path.join(os.path.dirname(__file__), "..", "kindle", "inkdoor")


def run(tmp_path, script, interval=300, path_dirs=()):
    """Sources common.sh with its Kindle folders moved into tmp_path, then runs ``script``."""
    home = tmp_path / "inkdoor"
    home.mkdir(exist_ok=True)
    with open(os.path.join(FOLDER, "config.sh")) as f:
        config = f.read().replace("INTERVAL=300", f"INTERVAL={interval}")
    (home / "config.sh").write_text(config)
    with open(os.path.join(FOLDER, "common.sh")) as f:
        # /tmp first: tmp_path itself is under /tmp on Linux, and must not be replaced again
        common = f.read().replace("/tmp/", f"{tmp_path}/").replace("/mnt/us/inkdoor", str(home))
        common = common.replace("/sys/", f"{tmp_path}/sys/")
    (home / "common.sh").write_text(common)
    # LC_ALL=C as on the Kindle: a UTF-8 locale makes some greps skip the PNG's binary header
    env = {**os.environ, "LC_ALL": "C",
           "PATH": os.pathsep.join([*map(str, path_dirs), os.environ["PATH"]])}
    return subprocess.run(["sh", "-c", f'. "{home}/common.sh"; {script}'], env=env, cwd=tmp_path,
                          capture_output=True, text=True, check=True).stdout.strip()


@pytest.mark.parametrize("headers, expected", [
    ("HTTP/1.1 200 OK\r\nX-Inkdoor-Next: 95\r\nContent-Type: image/png\r\n\r\n", "95"),
    ("HTTP/1.1 200 OK\r\nx-inkdoor-next: 120\r\n\r\n", "120"),       # any case
    ("  HTTP/1.1 200 OK\n  X-Inkdoor-Next: 61\n", "61"),              # wget -S indents headers
    ("HTTP/1.1 200 OK\r\nX-Inkdoor-Next: 3\r\n\r\n", "30"),          # never sooner than 30 s
    ("HTTP/1.1 200 OK\r\nX-Inkdoor-Next: 9000\r\n\r\n", "300"),      # never later than INTERVAL
    ("HTTP/1.1 200 OK\r\nX-Inkdoor-Next: 99999999999999999999\r\n\r\n", "300"),
    ("HTTP/1.1 200 OK\r\nX-Inkdoor-Next: soon\r\n\r\n", "300"),
    ("HTTP/1.1 200 OK\r\nContent-Type: image/png\r\n\r\n", "300"),   # an older server
])
def test_next_wait_follows_the_server_within_limits(tmp_path, headers, expected):
    (tmp_path / "inkdoor.headers").write_text(headers)
    assert run(tmp_path, "next_wait") == expected


def test_next_wait_without_a_download_is_the_interval(tmp_path):
    assert run(tmp_path, "next_wait", interval=600) == "600"


def test_download_keeps_the_response_headers(tmp_path):
    # a stand-in curl that answers like the server: headers to -D, a PNG to -o
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "curl").write_text('''#!/bin/sh
while [ $# -gt 0 ]; do
  case "$1" in
    -D) printf 'HTTP/1.1 200 OK\\r\\nX-Inkdoor-Next: 75\\r\\n\\r\\n' > "$2"; shift ;;
    -o) printf '\\211PNG\\r\\n' > "$2"; shift ;;
    -m) shift ;;
  esac
  shift
done
''')
    (bin_dir / "curl").chmod(0o755)
    assert run(tmp_path, "download && next_wait", path_dirs=[bin_dir]) == "75"
    assert (tmp_path / "inkdoor.png").read_bytes().startswith(b"\x89PNG")


# --- night light: apply_light -----------------------------------------------------------------

LIPC_GET = """#!/bin/sh
cat "{root}/level"
"""
LIPC_SET = """#!/bin/sh
[ -e "{root}/fail-set" ] && exit 1
echo "$*" >> "{root}/calls"
for last in "$@"; do :; done
echo "$last" > "{root}/level"
"""


@pytest.fixture
def lipc(tmp_path):
    """Stand-in lipc tools: get prints tmp_path/level, set records its call and stores the level."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("lipc-get-prop", LIPC_GET), ("lipc-set-prop", LIPC_SET)):
        (bin_dir / name).write_text(body.format(root=tmp_path))
        (bin_dir / name).chmod(0o755)
    (tmp_path / "level").write_text("12\n")
    return bin_dir


@pytest.fixture
def nodes(tmp_path):
    """Brightness files: the two in LIGHT_NODES (PW2/Voyage/PW3, PW1) and an amber node."""
    paths = {"pw2": "sys/class/backlight/max77696-bl/brightness",
             "pw1": "sys/devices/system/fl_tps6116x/fl_tps6116x0/fl_intensity",
             "amber": "sys/class/backlight/fp9966-bl0/brightness"}
    found = {}
    for key, rel in paths.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True)
        path.write_text("10\n")
        found[key] = path
    return found


def read(path):
    return path.read_text().strip()


def light_headers(tmp_path, value):
    (tmp_path / "inkdoor.headers").write_text(f"HTTP/1.1 200 OK\r\nX-Inkdoor-Light: {value}\r\n\r\n")


def saved(tmp_path):
    return tmp_path / "inkdoor" / "light-saved"


def save(tmp_path, text):
    (tmp_path / "inkdoor").mkdir(exist_ok=True)
    saved(tmp_path).write_text(text)


def test_light_off_saves_the_level_once_and_turns_everything_off(tmp_path, lipc, nodes):
    light_headers(tmp_path, "off")
    run(tmp_path, "apply_light", path_dirs=[lipc])
    assert read(saved(tmp_path)) == "12"
    assert (tmp_path / "calls").read_text() == "com.lab126.powerd flIntensity 0\n"
    assert read(nodes["pw2"]) == read(nodes["pw1"]) == "0"
    assert read(nodes["amber"]) == "10"                    # warm-light nodes are never touched
    assert "light off (saved level 12)" in (tmp_path / "inkdoor" / "log.txt").read_text()


def test_a_night_reboot_keeps_the_day_level(tmp_path, lipc, nodes):        # Review Focus 1
    save(tmp_path, "12\n")
    (tmp_path / "level").write_text("0\n")                 # powerd stored 0 before the reboot
    light_headers(tmp_path, "off")
    run(tmp_path, "apply_light", path_dirs=[lipc])
    assert read(saved(tmp_path)) == "12"
    light_headers(tmp_path, "on")
    run(tmp_path, "apply_light", path_dirs=[lipc])
    assert read(tmp_path / "level") == "12"
    assert not saved(tmp_path).exists()
    assert "light on (level 12)" in (tmp_path / "inkdoor" / "log.txt").read_text()


def test_light_off_at_level_0_skips_lipc_but_still_darkens_sysfs(tmp_path, lipc, nodes):
    save(tmp_path, "12\n")
    (tmp_path / "level").write_text("0\n")
    light_headers(tmp_path, "off")
    run(tmp_path, "apply_light", path_dirs=[lipc])
    assert not (tmp_path / "calls").exists()
    assert read(nodes["pw2"]) == read(nodes["pw1"]) == "0"


def test_light_off_leaves_sysfs_alone_when_lipc_fails(tmp_path, lipc, nodes):
    (tmp_path / "fail-set").write_text("")
    light_headers(tmp_path, "off")
    run(tmp_path, "apply_light", path_dirs=[lipc])
    assert read(saved(tmp_path)) == "12"                   # kept for the morning
    assert {read(p) for p in nodes.values()} == {"10"}


def test_light_on_without_a_saved_level_changes_nothing(tmp_path, lipc, nodes):
    light_headers(tmp_path, "on")
    run(tmp_path, "apply_light", path_dirs=[lipc])
    assert not (tmp_path / "calls").exists()
    assert {read(p) for p in nodes.values()} == {"10"}


def test_light_on_keeps_the_saved_level_when_lipc_fails(tmp_path, lipc):
    save(tmp_path, "12\n")
    (tmp_path / "fail-set").write_text("")
    light_headers(tmp_path, "on")
    run(tmp_path, "apply_light", path_dirs=[lipc])
    assert read(saved(tmp_path)) == "12"


def test_light_on_drops_a_saved_file_that_is_not_a_level(tmp_path, lipc):
    save(tmp_path, "garbage\n")
    light_headers(tmp_path, "on")
    run(tmp_path, "apply_light", path_dirs=[lipc])
    assert not saved(tmp_path).exists() and not (tmp_path / "calls").exists()


@pytest.mark.parametrize("raw", [
    "HTTP/1.1 200 OK\r\nContent-Type: image/png\r\n\r\n",       # an older server
    "HTTP/1.1 200 OK\r\nX-Inkdoor-Light: dim\r\n\r\n",
    "HTTP/1.1 200 OK\r\nX-Inkdoor-Light: OFF\r\n\r\n",          # values are lowercase
])
def test_light_ignores_missing_or_unknown_headers(tmp_path, lipc, nodes, raw):
    (tmp_path / "inkdoor.headers").write_text(raw)
    run(tmp_path, "apply_light", path_dirs=[lipc])
    assert not (tmp_path / "calls").exists() and not saved(tmp_path).exists()
    assert {read(p) for p in nodes.values()} == {"10"}


def test_light_without_a_download_changes_nothing(tmp_path, lipc, nodes):
    run(tmp_path, "apply_light", path_dirs=[lipc])         # no headers file at all
    assert not (tmp_path / "calls").exists() and not saved(tmp_path).exists()


@pytest.mark.parametrize("answer", ["", "abc", "-1"])
def test_light_off_without_a_readable_level_changes_nothing(tmp_path, lipc, nodes, answer):
    (tmp_path / "level").write_text(answer)
    light_headers(tmp_path, "off")
    run(tmp_path, "apply_light", path_dirs=[lipc])
    assert not (tmp_path / "calls").exists() and not saved(tmp_path).exists()
    assert {read(p) for p in nodes.values()} == {"10"}


def test_light_off_without_lipc_changes_nothing(tmp_path, nodes):
    light_headers(tmp_path, "off")
    run(tmp_path, "apply_light")                           # a Kindle without lipc on PATH
    assert not saved(tmp_path).exists()
    assert {read(p) for p in nodes.values()} == {"10"}


@pytest.mark.parametrize("raw", [
    "HTTP/1.1 200 OK\r\nx-inkdoor-light: off\r\n\r\n",          # any case
    "  HTTP/1.1 200 OK\n  X-Inkdoor-Light: off\n",                # wget -S indents headers
])
def test_light_reads_both_header_formats(tmp_path, lipc, raw):
    (tmp_path / "inkdoor.headers").write_text(raw)
    run(tmp_path, "apply_light", path_dirs=[lipc])
    assert read(saved(tmp_path)) == "12" and read(tmp_path / "level") == "0"


def test_light_keeps_the_loops_variables(tmp_path, lipc):
    light_headers(tmp_path, "off")
    out = run(tmp_path, 'count=7; failures=2; pause=60; n=5; apply_light; '
                        'echo "$count $failures $pause $n"', path_dirs=[lipc])
    assert out == "7 2 60 5"
