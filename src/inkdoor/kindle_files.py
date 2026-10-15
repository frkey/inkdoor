"""The Kindle's scripts as one zip, with config.sh already pointing at this server.

The scripts live in ``kindle/`` at the root of the repository, next to ``src/``; they are not part
of the Python package. Both supported installs keep them beside the code: the installer's
``/opt/inkdoor`` is a clone with its virtualenv inside, and a laptop runs ``pip install -e`` in a
clone. ``find_dir`` looks for them upwards from the package and returns None when they are not
there (for example, a package installed somewhere else), in which case the admin offers no zip.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

SCRIPTS = ("inkdoor/common.sh", "inkdoor/loop.sh", "inkdoor/config.sh",
           "documents/inkdoor-start.sh", "documents/inkdoor-test.sh")
# Inside the zip, the scriptlets go in "scriptlets/", not "documents/": dragging a folder named
# "documents" onto the Kindle in Finder can replace the Kindle's own, books included.
_ZIP_NAMES = {"documents/inkdoor-start.sh": "scriptlets/inkdoor-start.sh",
              "documents/inkdoor-test.sh": "scriptlets/inkdoor-test.sh"}
# What may go between the quotes of URL="..." in a shell file: an http address with no quotes,
# "$", backticks or backslashes
_SAFE_URL = re.compile(r"http://[A-Za-z0-9.:\[\]/_-]+")


def find_dir() -> Path | None:
    """The repository's ``kindle/`` folder, or None when this install does not have it."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "kindle"
        if all((candidate / name).is_file() for name in SCRIPTS):
            return candidate
    return None


def kindle_language(language: str) -> str:
    """The Kindle scripts know en-US and pt-BR (common.sh treats any "pt…" as pt-BR)."""
    return "pt-BR" if language.lower().startswith("pt") else "en-US"


def config_sh(template: str, url: str, language: str) -> str:
    """``config.sh`` with URL and LANGUAGE set; every other line as in the template."""
    if not _SAFE_URL.fullmatch(url):
        raise ValueError("unexpected characters in the image address")
    text = re.sub(r'^URL="[^"\n]*"', f'URL="{url}"', template, count=1, flags=re.M)
    return re.sub(r'^LANGUAGE="[^"\n]*"', f'LANGUAGE="{kindle_language(language)}"', text,
                  count=1, flags=re.M)


def build_zip(folder: Path, url: str, language: str, readme: str) -> bytes:
    """The zip the admin hands out: the scripts, config.sh filled in, and a README.txt."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in SCRIPTS:
            data = (folder / name).read_bytes()
            if name == "inkdoor/config.sh":
                data = config_sh(data.decode("utf-8"), url, language).encode("utf-8")
            info = zipfile.ZipInfo(_ZIP_NAMES.get(name, name), date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o100755 << 16          # a regular, executable file
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
        info = zipfile.ZipInfo("README.txt", date_time=(2026, 1, 1, 0, 0, 0))
        info.external_attr = 0o100644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, readme.replace("\n", "\r\n").encode("utf-8"))  # Notepad too
    return buffer.getvalue()
