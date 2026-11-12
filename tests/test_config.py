from pathlib import Path

import pytest

from inkdoor import config
from inkdoor.i18n import Translator

EXAMPLE = Path(__file__).resolve().parent.parent / "config.example.toml"


def write(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text)
    return str(path)


def test_defaults_and_language_override(tmp_path):
    cfg = config.load(write(tmp_path, '[display]\nlanguage = "en-US"\n'), language="pt-BR")
    assert cfg["display"]["language"] == "pt-BR"
    assert cfg["server"] == {"port": 3667, "refresh_minutes": 5}


INVALID = [
    ("[display\n", "syntax"),
    ('[display]\ntimezone = "Mars/Olympus"\n', "timezone"),
    ("[display]\nworkday_end = 25\n", "hour"),
    ("[display]\nworkdays = [7]\n", "workdays"),
    ('[display]\nclock = "13h"\n', "clock"),
    ("[server]\nrefresh_minutes = 0\n", "refresh"),
    ("[server]\nport = 70000\n", "port"),
    ('[[calendar]]\nurl = "x"\n', "calendar_name"),
    ('[[calendar]]\nname = "A"\n[[calendar]]\nname = "A"\n', "calendar_duplicate"),
    ('[[calendar]]\nname = "A"\nstyle = "dotted"\n', "style"),
    ('[admin]\nenabled = "yes"\n', "admin_enabled"),
    ('[admin]\nallowed_hosts = "door.example"\n', "allowed_hosts"),
    ('[admin]\nallowed_hosts = ["door.example:8000"]\n', "allowed_host"),
    ('[admin]\nallowed_hosts = ["[fd00::1]:8000"]\n', "allowed_host"),
    ('[admin]\nallowed_hosts = ["porta.exemplo-ç.com"]\n', "allowed_host"),
    ('admin = true\n', "section"),
    ('[display]\nscreen = "1080x1440"\n', "screen"),
    ('[display]\nlight_off = "22:00"\n', "light_pair"),
    ('[display]\nlight_on = "07:00"\n', "light_pair"),
    ('[display]\nlight_off = "7:00"\nlight_on = "07:00"\n', "light_time"),
    ('[display]\nlight_off = "22:00"\nlight_on = "7"\n', "light_time"),
    ('[display]\nlight_off = 22:00:00\nlight_on = "07:00"\n', "light_time"),   # Review Focus 2
    ('[display]\nlight_off = 22\nlight_on = "07:00"\n', "light_time"),          # Review Focus 2
    ('[display]\nlight_off = "22:00"\nlight_on = "22:00"\n', "light_same"),
    ('[display]\nscreen = 1072\n', "screen"),
]


@pytest.mark.parametrize("text, key", INVALID)
def test_invalid_values_are_explained(tmp_path, text, key):
    with pytest.raises(config.ConfigInvalid) as err:
        config.load(write(tmp_path, text))
    assert err.value.key == key


def test_light_schedule_loads(tmp_path):
    cfg = config.load(write(tmp_path, '[display]\nlight_off = "22:00"\nlight_on = "07:00"\n'))
    assert (cfg["display"]["light_off"], cfg["display"]["light_on"]) == ("22:00", "07:00")
    assert "light_off" not in config.load(write(tmp_path, "[display]\n"))["display"]


@pytest.mark.parametrize("language", ["en-US", "pt-BR"])
@pytest.mark.parametrize("text", [
    '[display]\nlight_off = "{secret}"\nlight_on = "07:00"\n',
    '[display]\nlight_off = "22:00"\n',
    '[display]\nlight_off = "22:00"\nlight_on = "22:00"\n',
])
def test_light_errors_translate_without_the_value(tmp_path, language, text):
    secret = "https://calendar.example/private-not-real.ics"
    with pytest.raises(config.ConfigInvalid) as err:
        config.load(write(tmp_path, text.replace("{secret}", secret)))
    message = Translator(language)(f"config_error.{err.value.key}", **err.value.details)
    assert secret not in message and "light_o" in message and "{" not in message


@pytest.mark.parametrize("language", ["en-US", "pt-BR"])
@pytest.mark.parametrize("text, key", INVALID)
def test_every_config_error_translates(tmp_path, language, text, key):
    # every caller translates with t(f"config_error.{ex.key}", **ex.details): a detail named "key"
    # must not clash with the translator's own parameter
    with pytest.raises(config.ConfigInvalid) as err:
        config.load(write(tmp_path, text))
    message = Translator(language)(f"config_error.{err.value.key}", **err.value.details)
    assert message and "{" not in message


@pytest.mark.parametrize("language", ["en-US", "pt-BR"])
def test_allowed_host_with_a_port_is_explained(tmp_path, language):
    with pytest.raises(config.ConfigInvalid) as err:
        config.load(write(tmp_path, '[admin]\nallowed_hosts = ["door.example:8000"]\n'))
    message = Translator(language)(f"config_error.{err.value.key}", **err.value.details)
    assert '"door.example:8000"' in message and "{" not in message


def test_allowed_hosts_accepts_names_and_addresses(tmp_path):
    hosts = '["door.example.com", "door.example.com.", "xn--prta-6qa.example", "fd00::1", "[fd00::1]"]'
    cfg = config.load(write(tmp_path, f"[admin]\nallowed_hosts = {hosts}\n"))
    assert len(cfg["admin"]["allowed_hosts"]) == 5


def test_admin_is_off_by_default(tmp_path):
    cfg = config.load(write(tmp_path, ""))
    assert cfg["admin"] == {"enabled": False, "allowed_hosts": []}
    cfg = config.load(write(tmp_path, '[admin]\nenabled = true\nallowed_hosts = ["door.example"]\n'))
    assert cfg["admin"] == {"enabled": True, "allowed_hosts": ["door.example"]}


def test_every_config_error_is_translated():
    from inkdoor.i18n import Translator
    for lang in ("en-US", "pt-BR"):
        t = Translator(lang)
        for key in t.get("config_error"):
            assert t.get(f"config_error.{key}")


def test_non_utf8_and_wrong_shapes_are_explained(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes('[[calendar]]\nname = "Família"\n'.encode("latin-1"))
    with pytest.raises(config.ConfigInvalid) as err:
        config.load(str(path))
    assert err.value.key == "encoding"
    for text in ('tasks = "x"\n', 'calendar = "x"\n', 'display = 3\n'):
        path.write_text(text)
        with pytest.raises(config.ConfigInvalid) as err:
            config.load(str(path))
        assert err.value.key == "section"


@pytest.mark.parametrize("text, key", [
    ('[[calendar]]\nname = "A"\nurl = 5\n', "calendar_url"),
    ('[[calendar]]\nname = "A"\nurl = ["https://calendar.example/secret.ics"]\n', "calendar_url"),
    ('[[calendar]]\nname = "A"\nbusy = "yes"\n', "calendar_busy"),
    ('[[calendar]]\nname = "A"\nbusy = 1\n', "calendar_busy"),
    ('[[calendar]]\nname = "A"\nstatus_label = 3\n', "calendar_label"),
    ('[tasks]\nurl = 5\n', "tasks_url"),
    ('[tasks]\nurl = { link = "https://tasks.example/secret.ics" }\n', "tasks_url"),
])
def test_hand_edited_value_types_are_explained(tmp_path, text, key):
    with pytest.raises(config.ConfigInvalid) as err:
        config.load(write(tmp_path, text))
    assert err.value.key == key
    assert "secret" not in repr(err.value.details)       # a link is never repeated back


def test_well_typed_calendar_and_tasks_load(tmp_path):
    cfg = config.load(write(tmp_path, '[[calendar]]\nname = "A"\nurl = "https://calendar.example/a.ics"\n'
                                      'busy = false\nstatus_label = "Out"\n\n'
                                      '[[calendar]]\nname = "B"\n\n'
                                      '[tasks]\nurl = "https://tasks.example/t.ics"\n'))
    assert cfg["calendar"][0]["busy"] is False and "url" not in cfg["calendar"][1]


def test_example_leaves_the_door_word_to_the_language():
    # real configs start from the example (copied by hand, and whole by the first installer), and
    # a status_label is shown as written: it would put English on a pt-BR door
    cfg = config.load(str(EXAMPLE), language="pt-BR")
    assert [c.get("status_label") for c in cfg["calendar"]] == [None] * len(cfg["calendar"])


@pytest.mark.parametrize("value", [None, "", 5, ["x"], {"a": 1}, True])
def test_is_configured_is_false_for_anything_but_a_real_link(value):
    assert config.is_configured(value) is False


def test_is_configured_needs_a_non_placeholder_string():
    assert config.is_configured("https://calendar.example/a.ics")
    assert not config.is_configured(config.PLACEHOLDER_PREFIX + "YOUR_LINK")
