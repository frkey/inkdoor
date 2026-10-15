import os

from inkdoor.__main__ import main


def test_demo_with_options_before_and_after_the_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)       # no config.toml here
    monkeypatch.delenv("INKDOOR_LANG", raising=False)
    assert main(["-o", "a", "demo", "9:00"]) == 0
    assert main(["demo", "9:00", "-o", "b", "--lang", "pt-BR"]) == 0
    assert os.path.exists(tmp_path / "a" / "demo-en-US-900.png")
    assert os.path.exists(tmp_path / "b" / "demo-pt-BR-900.png")
    assert "INKDOOR_LANG" not in os.environ   # --lang does not leak into the process


def test_missing_config_exits_with_2(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("INKDOOR_LANG", raising=False)
    assert main(["check"]) == 2
    assert "config.example.toml" in capsys.readouterr().err


def test_invalid_config_is_explained_in_the_chosen_language(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text("[server]\nrefresh_minutes = 0\n")
    assert main(["render", "--lang", "pt-BR"]) == 2
    assert "refresh_minutes precisa ser" in capsys.readouterr().err
