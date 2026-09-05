"""Module entry point for guarded AT-SPI actions (ADR-0026 D3).

Run by the kernel as a fixed-argv PlannedStep:

    python -m jarvis.gui.action_exec --app <app> --role <role> --name <name> \
        (--action <name> | --text <string> | --list)

One JSON result line on stdout; honest exit codes: 0 ok · 2 refused by a
wall · 3 not found. pyatspi is imported lazily so absence stays an honest
capability gap (distro package python3-pyatspi).
"""

from __future__ import annotations

import argparse
import json
import sys

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_NOT_FOUND = 3


def _desktop() -> object:
    import pyatspi  # type: ignore[import-not-found]

    return pyatspi.Registry.getDesktop(0)


def main(argv: list[str] | None = None) -> int:
    from jarvis.gui.actions import (
        ActionRefused,
        do_named_action,
        find_node,
        list_actions,
        set_node_text,
    )

    parser = argparse.ArgumentParser(prog="jarvis.gui.action_exec", description=__doc__)
    parser.add_argument("--app", required=True, help="target application (AT-SPI application name)")
    parser.add_argument("--role", required=True, help="target node AT-SPI role (e.g. push button)")
    parser.add_argument("--name", required=True, help="target node name (exact, case-insensitive)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--action", help="invoke this published action (e.g. click, press)")
    group.add_argument("--text", help="write this text via the EditableText interface")
    group.add_argument("--list", action="store_true", help="print the node's published actions")
    args = parser.parse_args(argv)

    try:
        node = find_node(_desktop(), app=args.app, role=args.role, name=args.name)
        if args.list:
            print(json.dumps({"ok": True, "actions": list_actions(node.node)}))
            return EXIT_OK
        if args.action:
            performed = do_named_action(node.node, args.action)
            print(json.dumps({"ok": True, "performed": performed}))
            return EXIT_OK
        detail = set_node_text(node.node, args.text or "")
        print(json.dumps({"ok": True, "detail": detail}))
        return EXIT_OK
    except ActionRefused as exc:
        message = str(exc)
        print(json.dumps({"ok": False, "refused": message}))
        print(f"refused: {message}", file=sys.stderr)
        walled = "blocked list" in message or "password" in message
        return EXIT_REFUSED if walled else EXIT_NOT_FOUND
    except Exception as exc:  # unavailability is honest, never a crash in a kernel step
        print(json.dumps({"ok": False, "error": f"AT-SPI unavailable or failed: {exc}"}))
        return EXIT_NOT_FOUND


if __name__ == "__main__":
    raise SystemExit(main())
