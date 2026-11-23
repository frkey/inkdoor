"""The Kindle's shell helpers (kindle/inkdoor/common.sh), run with sh on this computer."""
import os
import shutil
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


@pytest.mark.parametrize("bad", ["", "garbage\n"])
def test_light_off_replaces_a_saved_file_that_is_not_a_level(tmp_path, lipc, nodes, bad):
    save(tmp_path, bad)                                    # e.g. a write that failed on full storage
    light_headers(tmp_path, "off")
    run(tmp_path, "apply_light", path_dirs=[lipc])
    assert read(saved(tmp_path)) == "12"
    light_headers(tmp_path, "on")
    run(tmp_path, "apply_light", path_dirs=[lipc])
    assert read(tmp_path / "level") == "12"                # the morning still brings it back


def test_light_off_never_saves_a_level_of_0(tmp_path, lipc, nodes):
    # with no valid saved level and the light already at 0 there is nothing to bring back; saving 0
    # would make the morning "restore" darkness (e.g. after a save lost to a power cut)
    (tmp_path / "level").write_text("0\n")
    light_headers(tmp_path, "off")
    run(tmp_path, "apply_light", path_dirs=[lipc])
    assert not saved(tmp_path).exists() and not (tmp_path / "calls").exists()
    assert read(nodes["pw2"]) == read(nodes["pw1"]) == "0"


# --- staying awake: keep_awake ----------------------------------------------------------------

POWERD_GET = """#!/bin/sh
[ "$1" = com.lab126.powerd ] && [ -f "{root}/powerd/$2" ] || exit 1
cat "{root}/powerd/$2"
"""
POWERD_SET = """#!/bin/sh
[ -e "{root}/fail-set" ] && exit 1
echo "$*" >> "{root}/calls"
[ "$2" = preventScreenSaver ] && echo "$3" > "{root}/powerd/preventScreenSaver"
exit 0
"""
# date +%s reads tmp_path/now, so the hourly line can be tested; other formats are the real date's
FAKE_DATE = """#!/bin/sh
if [ "$1" = "+%s" ]; then cat "{root}/now"; else exec "{date}" "$@"; fi
"""


@pytest.fixture
def powerd(tmp_path):
    """Stand-in lipc tools answering powerd's properties from tmp_path/powerd/<name>."""
    bin_dir = tmp_path / "powerd-bin"
    bin_dir.mkdir()
    for name, body in (("lipc-get-prop", POWERD_GET), ("lipc-set-prop", POWERD_SET),
                       ("date", FAKE_DATE)):
        (bin_dir / name).write_text(body.format(root=tmp_path, date=shutil.which("date")))
        (bin_dir / name).chmod(0o755)
    props = tmp_path / "powerd"
    props.mkdir()
    for name, value in (("state", "active"), ("preventScreenSaver", "1"), ("battLevel", "100"),
                        ("isCharging", "1")):
        (props / name).write_text(value + "\n")
    (tmp_path / "now").write_text("1000000\n")
    return bin_dir


def power_lines(tmp_path):
    log = tmp_path / "inkdoor" / "log.txt"
    text = log.read_text() if log.exists() else ""
    return [line.split(" ", 2)[2] for line in text.splitlines() if " power: " in line]


def calls(tmp_path):
    path = tmp_path / "calls"
    return path.read_text().splitlines() if path.exists() else []


def test_keep_awake_sets_the_property_back_when_something_cleared_it(tmp_path, powerd):
    # contentpackd sets preventScreenSaver to 0 after updating fonts, whatever it was before
    (tmp_path / "powerd" / "preventScreenSaver").write_text("0\n")
    run(tmp_path, "keep_awake", path_dirs=[powerd])
    assert "com.lab126.powerd preventScreenSaver 1" in calls(tmp_path)
    assert read(tmp_path / "powerd" / "preventScreenSaver") == "1"
    assert power_lines(tmp_path) == ["power: state=active prevent=0 battery=100 charging=1"]


def test_keep_awake_restarts_the_idle_timer_on_every_pass(tmp_path, powerd):
    run(tmp_path, "keep_awake; keep_awake", path_dirs=[powerd])
    assert calls(tmp_path) == ["com.lab126.powerd touchScreenSaverTimeout 1"] * 2


def test_keep_awake_logs_changes_not_every_pass(tmp_path, powerd):
    run(tmp_path, "keep_awake; keep_awake; echo 0 > powerd/isCharging; keep_awake; keep_awake; "
                  "echo screenSaver > powerd/state; keep_awake", path_dirs=[powerd])
    assert power_lines(tmp_path) == ["power: state=active prevent=1 battery=100 charging=1",
                                     "power: state=active prevent=1 battery=100 charging=0",
                                     "power: state=screenSaver prevent=1 battery=100 charging=0"]


def test_keep_awake_logs_the_battery_in_steps_of_ten(tmp_path, powerd):
    steps = "; ".join(f"echo {level} > powerd/battLevel; keep_awake" for level in (95, 91, 89, 80, 79))
    run(tmp_path, steps, path_dirs=[powerd])
    assert [line.split()[3] for line in power_lines(tmp_path)] == [
        "battery=95", "battery=89", "battery=79"]


def test_keep_awake_logs_once_an_hour_when_nothing_changes(tmp_path, powerd):
    run(tmp_path, "keep_awake; echo 1003599 > now; keep_awake; echo 1003600 > now; keep_awake; "
                  "echo 1003000 > now; keep_awake",            # a clock set back also logs
        path_dirs=[powerd])
    assert len(power_lines(tmp_path)) == 3


def test_keep_awake_tries_again_when_setting_the_property_fails(tmp_path, powerd):
    (tmp_path / "powerd" / "preventScreenSaver").write_text("0\n")
    (tmp_path / "fail-set").write_text("")
    run(tmp_path, "keep_awake; rm fail-set; keep_awake", path_dirs=[powerd])
    assert calls(tmp_path) == ["com.lab126.powerd touchScreenSaverTimeout 1",
                               "com.lab126.powerd preventScreenSaver 1"]


def test_keep_awake_logs_only_letters_and_digits(tmp_path, powerd):
    (tmp_path / "powerd" / "state").write_text("active\r\n")
    (tmp_path / "powerd" / "battLevel").write_text(" 87 %\n")
    (tmp_path / "powerd" / "isCharging").write_text("1; rm -rf /\n")
    run(tmp_path, "keep_awake", path_dirs=[powerd])
    assert power_lines(tmp_path) == ["power: state=active prevent=1 battery=87 charging=1rmrf"]


def test_keep_awake_without_lipc_still_returns(tmp_path):
    assert run(tmp_path, "keep_awake && echo ok") == "ok"        # a Kindle without lipc on PATH
    assert power_lines(tmp_path) == ["power: state=? prevent=? battery=? charging=?"]


def test_keep_awake_keeps_the_loops_variables(tmp_path, powerd):
    out = run(tmp_path, 'count=7; failures=2; pause=60; n=5; i=3; keep_awake; '
                        'echo "$count $failures $pause $n $i"', path_dirs=[powerd])
    assert out == "7 2 60 5 3"
