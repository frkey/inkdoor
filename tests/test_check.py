import os

import pytest
from conftest import FIXTURES, at

from inkdoor.check import run


@pytest.mark.parametrize("language", ["en-US", "pt-BR"])
def test_check_output_matches_golden(cfg, capsys, language):
    cfg["display"]["language"] = language
    assert run(cfg, now=at("09:00")) is True
    expected = open(os.path.join(FIXTURES, f"check-golden-{language}.txt"), encoding="utf-8").read()
    assert capsys.readouterr().out == expected
