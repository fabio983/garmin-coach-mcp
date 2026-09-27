"""CLI: python -m app [serve|login|sync|reparse]"""
import argparse
import json
import logging

from . import config, db


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="garmin-coach")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="run the MCP server + periodic sync (default)")
    sub.add_parser("login", help="interactive Garmin login (MFA supported)")
    s = sub.add_parser("sync", help="manual sync")
    s.add_argument("--full", action="store_true", help=f"everything since BACKFILL_FROM ({config.BACKFILL_FROM})")
    s.add_argument("--since", help="from YYYY-MM-DD")
    s.add_argument("--redetail", action="store_true", help="re-download FIT files already stored")
    sub.add_parser("reparse", help="rebuild laps/records from stored FIT files")
    a = p.parse_args()

    if a.cmd == "login":
        from .garmin import interactive_login
        interactive_login()
    elif a.cmd == "sync":
        from . import sync
        print(json.dumps(sync.run(since=a.since, full=a.full, redetail=a.redetail), indent=2, ensure_ascii=False))
    elif a.cmd == "reparse":
        from . import sync
        print(f"FIT files reprocessed: {sync.reparse_all()}")
    else:
        db.init()
        from .server import serve
        serve()


if __name__ == "__main__":
    main()
