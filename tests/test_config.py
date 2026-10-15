import pytest

from inkdoor import config


def write(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text)
    return str(path)


def test_defaults_and_language_override(tmp_path):
    cfg = config.load(write(tmp_path, '[display]\nlanguage = "en-US"\n'), language="pt-BR")
    assert cfg["display"]["language"] == "pt-BR"
    assert cfg["server"] == {"port": 8000, "refresh_minutes": 5}


@pytest.mark.parametrize("text, key", [
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
])
def test_invalid_values_are_explained(tmp_path, text, key):
    with pytest.raises(config.ConfigInvalid) as err:
        config.load(write(tmp_path, text))
    assert err.value.key == key


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
