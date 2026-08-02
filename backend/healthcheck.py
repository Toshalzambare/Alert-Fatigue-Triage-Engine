"""Pretty-print /api/health. Used by run.sh; also useful on its own.

    ./venv/bin/python healthcheck.py

Exits 0 if the backend answered, 1 if it did not - so run.sh can gate on it.
"""
import json
import sys
import urllib.request

import config

URL = f"http://{config.HOST}:{config.PORT}/api/health"


def main() -> int:
    try:
        with urllib.request.urlopen(URL, timeout=5) as r:
            h = json.loads(r.read())
    except Exception as exc:  # noqa: BLE001
        print(f"    backend unreachable at {URL} ({exc})")
        return 1

    for name, s in h["subsystems"].items():
        mark = "OK  " if s["status"] in ("ok", "configured") else "STUB"
        print(f"    [{mark}] {name:<9} {s['status']}")
    print(f"    mode={h['config']['mode']}  ready={h['ready']}")
    if h["degraded"]:
        print(f"    degraded: {', '.join(h['degraded'])} (expected until B/C/D land)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
