"""python -m mealplan web [--port 8796]  |  mcp [--port 8797]"""

from __future__ import annotations

import argparse
import logging
import sys


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if len(sys.argv) < 2 or sys.argv[1] not in ("web", "mcp"):
        sys.exit(__doc__)
    if sys.argv[1] == "mcp":
        from .mcp_server import main as mcp_main

        mcp_main(sys.argv[2:])
        return
    import uvicorn

    from .web import create_app

    p = argparse.ArgumentParser(prog="mealplan web")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8796)
    a = p.parse_args(sys.argv[2:])
    # proxy_headers: nginx sets X-Forwarded-For, and only loopback is trusted.
    uvicorn.run(create_app(), host=a.host, port=a.port, proxy_headers=True, forwarded_allow_ips="127.0.0.1")


if __name__ == "__main__":
    main()
