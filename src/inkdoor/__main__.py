"""inkdoor command line.

    inkdoor serve            render every few minutes and serve http://<ip>:8000/kindle.png
    inkdoor render           render once (output/kindle.png)
    inkdoor check            test every calendar link
    inkdoor demo [HH:MM...]  render previews with fictional data
"""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__, config
from .i18n import Translator, available


def main(argv: list[str] | None = None) -> int:
    # global options work both before and after the command (inkdoor -o x demo / inkdoor demo -o x)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", "-c", default=argparse.SUPPRESS,
                        help="path to config.toml (default: ./config.toml)")
    common.add_argument("--output", "-o", default=argparse.SUPPRESS,
                        help="where images are written (default: ./output)")
    common.add_argument("--lang", choices=available(), default=argparse.SUPPRESS,
                        help="language for the screen and messages (overrides the config)")

    parser = argparse.ArgumentParser(prog="inkdoor", parents=[common],
                                     description="E-ink calendar display for your door.")
    parser.add_argument("--version", action="version", version=f"inkdoor {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", parents=[common], help="render and serve the screen continuously")
    commands.add_parser("render", parents=[common], help="render the screen once")
    commands.add_parser("check", parents=[common], help="test the calendar links")
    demo = commands.add_parser("demo", parents=[common], help="render previews with fictional data")
    demo.add_argument("hours", nargs="*", default=["16:50"], help="one or more times, e.g. 10:20 15:20")
    args = parser.parse_args(argv)
    args.config = getattr(args, "config", None)
    args.output = getattr(args, "output", "output")
    args.lang = getattr(args, "lang", None)

    if args.lang:
        os.environ["INKDOOR_LANG"] = args.lang   # config.load() applies it
    language = os.environ.get("INKDOOR_LANG")

    try:
        if args.command == "demo":
            from .demo import demo_config, demo_snapshot
            from .render import render
            from .server import save
            try:
                lang = config.load(args.config)["display"]["language"]
            except config.ConfigMissing:
                lang = language
            cfg = demo_config(lang)
            t = Translator(cfg["display"]["language"])
            for hour in args.hours:
                path = os.path.join(args.output, f"demo-{cfg['display']['language']}-{hour.replace(':', '')}.png")
                save(render(demo_snapshot(cfg, hour), cfg), path)
                print(t("cli.preview", path=path))
            return 0

        if args.command == "check":
            from .check import run
            return 0 if run(config.load(args.config)) else 1

        if args.command == "render":
            from .server import render_once
            render_once(config.load(args.config), args.output)
            return 0

        if args.command == "serve":
            from .server import serve
            serve(args.config, args.output)
            return 0
    except config.ConfigMissing as ex:
        print(Translator(language)("cli.config_missing", path=ex.path), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
