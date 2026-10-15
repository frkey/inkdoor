"""State shared by the render loop and the admin app."""
from __future__ import annotations

import datetime as dt
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, ClassVar

IMAGE_NAME = "kindle.png"  # the file the render loop writes and /kindle.png serves


@dataclass
class RenderInfo:
    """Summary of the last render, shown on the admin home page."""
    at: dt.datetime
    word: str
    headline: str
    errors: list[str]


@dataclass
class ServerState:
    """What the render thread and the request threads share.

    Only the render thread renders: the admin asks for a render with ``request_render``, which
    sets ``render_event``. ``write_lock`` serializes config writes.
    """
    MANUAL_INTERVAL: ClassVar[float] = 30.0

    config_path: str
    output_dir: str
    language: str | None
    cfg: dict = field(repr=False)  # holds the secret calendar links
    config_problem: str | None = None  # None, "broken" or "missing"
    admin_enabled: bool = False
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    render_event: threading.Event = field(default_factory=threading.Event, repr=False)
    write_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    last_render: RenderInfo | None = None
    _manual_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _last_manual: float | None = field(default=None, init=False, repr=False)

    def request_render(self, manual: bool = False) -> bool:
        """Wakes the render loop. Manual requests ("Update now") are limited to one per 30 s;
        returns False when this one was throttled."""
        if manual:
            with self._manual_lock:
                now = self.clock()
                if self._last_manual is not None and now - self._last_manual < self.MANUAL_INTERVAL:
                    return False
                self._last_manual = now
        self.render_event.set()
        return True
