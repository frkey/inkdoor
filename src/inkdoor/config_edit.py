"""Edits config.toml as it is on disk, for the admin pages.

The admin works on the raw TOML dict, never on ``config.load()`` output, so defaults and
``--lang`` / ``INKDOOR_LANG`` overrides are never written into the file. Every save carries the
digest of the file as it was read and is refused if the file changed in the meantime.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import os
from dataclasses import dataclass

import tomli_w

from . import config
from .files import write_private

BACKUP_SUFFIX = ".bak"


class ConfigChanged(Exception):
    """The file changed since it was read (a hand edit or another browser tab)."""


@dataclass
class RawConfig:
    data: dict
    digest: str
    exists: bool


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_raw(path) -> RawConfig:
    """The file's data without defaults, and the digest of the exact bytes read.

    A missing file reads as empty, so the first save creates it.
    """
    try:
        data, raw = config.read_toml(path)
    except config.ConfigMissing:
        return RawConfig({}, digest(b""), False)
    return RawConfig(data, digest(raw), True)


def check(data: dict) -> dict:
    """Validates a copy of ``data`` with the defaults filled in, and returns that copy."""
    cfg = config.check_sections(copy.deepcopy(data))
    return config.validate(config.with_defaults(cfg))


def save(path, data: dict, expected_digest: str) -> str:
    """Validates and writes ``data``; the previous file becomes the backup. Returns the new digest."""
    check(data)
    return _replace(path, tomli_w.dumps(data).encode("utf-8"), expected_digest)


def restore_backup(path, expected_digest: str) -> str:
    """Puts the backup back. The file it replaces becomes the new backup, so this can be undone."""
    backup = os.fspath(path) + BACKUP_SUFFIX
    try:
        data, raw = config.read_toml(backup)
    except config.ConfigMissing:
        raise config.ConfigInvalid("unreadable", path=backup, error="FileNotFoundError") from None
    check(data)
    return _replace(path, raw, expected_digest)


def _replace(path, new: bytes, expected_digest: str) -> str:
    path = os.fspath(path)
    try:
        old = config.read_bytes(path)
    except config.ConfigMissing:
        old = None
    if not hmac.compare_digest(digest(old or b""), expected_digest):
        raise ConfigChanged()
    if old is not None:
        write_private(path + BACKUP_SUFFIX, old)
    write_private(path, new)
    return digest(new)
