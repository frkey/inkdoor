"""The Home page: what the door says and when it changes next, today's timeline, each source's
state, the door's preview, "Update now", the status the preview polls, and restoring the
previous config."""
from __future__ import annotations

import datetime as dt

from flask import Blueprint, abort, g, jsonify, make_response, redirect, render_template, request

from .. import config, config_edit, kindle_files, light, net
from ..config import is_configured
from ..render import screen_size
from . import add_notice
from .editing import Editor


def _nothing_configured(data: dict) -> bool:
    """True when no calendar and no task list has a link: the door shows the setup screen."""
    tasks = data.get("tasks") or {}
    return not any(is_configured(c.get("url")) for c in data.get("calendar", [])) and \
        not is_configured(tasks.get("url"))


TIMELINE_WIDTH = 1000     # the timeline's box; the template prints positions as tenths of a percent
MIN_BLOCK = 4             # the narrowest a block is drawn, so a 5-minute event is still seen


def source_rows(t, sources) -> list[dict]:
    """Each source's state for the Sources card, in words: never a link or an exception's text."""
    rows = []
    for source in sources:
        reason = t(f"admin.reason_{source.reason}") if source.reason else ""
        if source.state == "ok":
            key = "admin.tasks_ok" if source.kind == "tasks" else "admin.source_ok"
            sentence = t(key, n=source.items, time=t.time(source.read_at))
        elif source.state == "stale" and source.read_at is not None:
            sentence = t("admin.source_stale", reason=reason, time=t.time(source.read_at))
        elif source.state in ("stale", "failed"):
            sentence = t("admin.source_failed", reason=reason)
        else:
            sentence = t("admin.link_not_set")
        rows.append({"name": source.name, "style": source.style, "kind": source.kind,
                     "state": source.state, "state_text": t(f"admin.state_{source.state}"),
                     "sentence": sentence})
    return rows


def timeline_view(t, timeline, now: dt.datetime) -> dict | None:
    """The workday as the template draws it: positions in a box TIMELINE_WIDTH wide."""
    if timeline is None:
        return None
    total = (timeline.end - timeline.start).total_seconds()
    if total <= 0:
        return None

    def x(moment: dt.datetime) -> int:
        return round((moment - timeline.start).total_seconds() / total * TIMELINE_WIDTH)

    blocks = []
    for block in timeline.blocks:
        width = max(x(block.end) - x(block.start), MIN_BLOCK)
        blocks.append({"x": min(x(block.start), TIMELINE_WIDTH - width), "w": width,
                       "style": block.style, "busy": block.busy})
    # a label at both ends and every second hour between (every fourth on a long day), leaving
    # out one that would sit against the end
    step = dt.timedelta(hours=2 if total <= 12 * 3600 else 4)
    ticks, moment = [timeline.start], timeline.start + step
    while moment + step / 2 < timeline.end:
        ticks.append(moment)
        moment += step
    ticks.append(timeline.end)
    periods = ", ".join(f"{t.time(b.start)}–{t.time(b.end)}" for b in timeline.blocks if b.busy)
    return {"width": TIMELINE_WIDTH, "blocks": blocks,
            "now_x": x(now) if timeline.start <= now <= timeline.end else None,
            "ticks": [(t.time(tick), x(tick)) for tick in ticks],
            "summary": t("admin.timeline_alt", periods=periods) if periods
            else t("admin.timeline_none")}


def status_facts(t, last, next_render_at: float | None, last_fetch_at: float | None,
                 now: float, known: bool = True) -> list[str]:
    """The lines under the door's status: its next change (only while the status is ``known``:
    the line names the next word), the last and next update, and when a Kindle last fetched
    the image. ``now`` and the two times are wall time."""
    facts = []
    if known and last.next_change is not None:
        when = t.time(last.next_change)
        if last.next_word and last.next_word != last.word:
            facts.append(t("admin.next_change_to", word=last.next_word, time=when))
        else:
            facts.append(t("admin.next_change", time=when))
    facts.append(t("admin.last_update", date=t.date_short(last.at), time=t.time(last.at)))
    if next_render_at is not None and next_render_at > now:
        facts.append(t("admin.next_update",
                       time=t.time(dt.datetime.fromtimestamp(next_render_at, last.at.tzinfo))))
    if last_fetch_at is None:
        facts.append(t("admin.last_fetch_never"))
    else:
        minutes = int(max(0.0, now - last_fetch_at) // 60)
        facts.append(t("admin.last_fetch", duration=t.duration(minutes)) if minutes
                     else t("admin.last_fetch_now"))
    return facts


def register(bp: Blueprint, ed: Editor) -> None:
    state, t = ed.state, ed.t

    def kindle_url() -> str | None:
        """The image address for other devices on the network, as Home shows it."""
        base = net.admin_url(state.cfg)
        return base + "/kindle.png" if base else None

    def preview_caption() -> str | None:
        """The night light's hours, under the preview, when a schedule is set."""
        times = light.schedule(state.cfg)
        if times is None:
            return None
        return t()("admin.preview_light", off=t().time(times[0]), on=t().time(times[1]))

    def updated_text(last) -> str | None:
        if last is None:
            return None
        return t()("admin.last_update", date=t().date_short(last.at), time=t().time(last.at))

    @bp.get("/")
    def home():
        last = state.last_render
        raw, problem = ed.read()
        warning = ed.invalid(raw.data) if raw is not None else None
        # from the file as it is now: state.config_problem lags until the next render, so a
        # restore or a first save would otherwise still show the old banner
        missing = raw is not None and not raw.exists
        broken = bool(problem or warning) or (missing and state.config_problem == "broken")
        url = kindle_url()
        now = ed.clock()
        timeline = last.timeline if last is not None else None
        return render_template(
            "home.html", active="home", last=last,
            # "door" in the template is the status as far as anybody knows it (door_status)
            facts=status_facts(t(), last, state.next_render_at, state.last_fetch_at, now,
                               known=state.image_current(now))
            if last is not None else [],
            sources=source_rows(t(), last.sources) if last is not None else [],
            timeline=timeline_view(t(), timeline, dt.datetime.fromtimestamp(
                now, timeline.start.tzinfo)) if timeline is not None else None,
            caption=preview_caption(),
            preview=ed.preview_token(), at=last.at.isoformat() if last is not None else "",
            poll=ed.watching(),
            kindle_url=url, screen=screen_size(state.cfg),
            # the zip needs the address it writes into config.sh, and the scripts beside the code
            kindle_zip=url is not None and kindle_files.find_dir() is not None,
            port=state.cfg["server"]["port"], broken=broken, problem=problem or warning,
            using_defaults=state.using_defaults,
            # the door's own rule for its setup screen; a missing file is a first setup too
            first_setup=not broken and raw is not None and _nothing_configured(raw.data),
            restore=ed.restore_offer(raw, problem, warning))

    @bp.get("/kindle-files.zip")
    def kindle_zip():
        """The Kindle's scripts, with config.sh already pointing at this server."""
        url, folder = kindle_url(), kindle_files.find_dir()
        if url is None or folder is None:
            abort(404)
        docs = "docs/pt-BR/kindle.md" if t().language.startswith("pt") else "docs/kindle.md"
        readme = t()("kindle_zip.readme", url=url,
                     docs=f"https://github.com/frkey/inkdoor/blob/master/{docs}")
        response = make_response(kindle_files.build_zip(folder, url, t().language, readme))
        response.mimetype = "application/zip"
        response.headers["Content-Disposition"] = 'attachment; filename="inkdoor-kindle.zip"'
        return response

    @bp.get("/status.json")
    def status():
        last = state.last_render
        return jsonify(at=last.at.isoformat() if last is not None else None,
                       word=last.word if last is not None else None,
                       headline=last.headline if last is not None else None,
                       updated=updated_text(last),
                       errors=list(last.errors) if last is not None else [])

    @bp.post("/render")
    def render_now():
        requested = state.request_render(manual=True)
        if requested:
            g.session.flags.add("watch_render")
        key = "admin.update_requested" if requested else "admin.update_throttled"
        add_notice(g.session, t()(key))
        return redirect("/", 303)

    @bp.post("/restore")
    def restore():
        try:
            config_edit.restore_backup(state.config_path, request.form.get("digest"))
        except config_edit.ConfigChanged:
            return ed.changed("/")
        except config_edit.ConfigIsLink:
            add_notice(g.session, t()("admin.error_link"))
            return redirect("/", 303)
        except config.ConfigInvalid as ex:
            add_notice(g.session, t()("admin.restore_failed", message=ed.describe(ex)))
            return redirect("/", 303)
        except OSError as ex:
            add_notice(g.session, t()("admin.error_write", error=type(ex).__name__))
            return redirect("/", 303)
        state.request_render()
        g.session.flags.add("watch_render")
        add_notice(g.session, t()("admin.restored"))
        return redirect("/", 303)
