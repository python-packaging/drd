import json
import re
import sqlite3
import sys
import time
import xmlrpc.client
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

import requests
from packaging.utils import canonicalize_name

RESET_RE = re.compile(r"Limit may reset in (\d+) second")

CACHE_PATH = Path("~/.cache/honesty").expanduser()
SERIAL_CACHE_PATH = CACHE_PATH / "serials"
MIRROR_DB_PATH = Path("db/mirror.db")

PYPI_API_BASE = "https://pypi.org/pypi"
PYPI_BASE = "https://pypi.org/simple/"
XMLRPC_HEADERS = [
    ("User-Agent", "https://github.com/python-packaging/drd by tshatch@gmail.com"),
]


def handle_retry(func):
    while True:
        try:
            return func()
        except xmlrpc.client.Fault as e:
            if "-32500" in repr(e):
                m = RESET_RE.search(repr(e))
                if m:
                    print("Backoff", m.group(1), file=sys.stderr)
                    time.sleep(int(m.group(1)) + 1)
                else:
                    print("Backoff 90", file=sys.stderr)
                    time.sleep(90)
            else:
                raise


CLIENT = xmlrpc.client.ServerProxy(PYPI_API_BASE, headers=XMLRPC_HEADERS)


class DrdState:

    def update_mirror(self):
        """
        Updates 3 things:
        * sqlite db of events
        * json and owner metadata, keeping the last 3 per project
        * mapping of names to serial (to discover admin deletion timestamps)

        Notably it does not do the deletion discovery; this is the
        time-sensitive part while deletion discovery is not.
        """
        self._update_changelog()

    def _update_changelog(self):
        conn = sqlite3.connect(MIRROR_DB_PATH)
        row = conn.execute("select max(serial) from changelog;").fetchone()
        serial = row[0] or 0
        latest_serial = handle_retry(CLIENT.changelog_last_serial)

        while serial < latest_serial:
            print(f"changelog_since_serial({serial}), {latest_serial-serial} to go")

            # name, version, timestamp, action, serial
            events = handle_retry(lambda: CLIENT.changelog_since_serial(serial))

            # <stuff>, cn, user
            for i in range(len(events)):
                parts = events[i][3].split()
                if len(parts) == 3 and parts[1] in ("Owner", "Maintainer"):
                    user_involved = parts[2]
                else:
                    user_involved = None
                events[i] = [*events[i], canonicalize_name(events[i][0]), user_involved]

            conn.executemany(
                "insert into changelog (name, version, timestamp, action, serial, cn, user_involved) values (?, ?, ?, ?, ?, ?, ?)",
                events,
            )
            conn.commit()

            if events:
                serial = events[-1][4]
            else:
                # Shouldn't happen, but prevent infinite loop if so
                break

if __name__ == "__main__":
    DrdState().update_mirror()
