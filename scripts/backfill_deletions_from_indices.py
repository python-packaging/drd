import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pytz
import requests
from packaging.utils import canonicalize_name
from pytz import timezone

LINK_RE = re.compile(r'"/simple/([^"/]+)/"[^>]*>([^<]+)</')
SERIAL_RE = re.compile(r"SERIAL (\d+)")

# This public mirror was created ~Nov 3 2019, and both caches and does not
# delete json metadata.  Wonderful, my simple index snapshots started Oct 30 so
# this has most of what I've observed.
MIRROR_URL = "http://mirrors6.hit.edu.cn/pypi/web/pypi/%s/json"
LIVE_URL = "https://pypi.org/pypi/%s/json"
DELETIONS_JSON_PATH = Path("data/deletions.json")


def cache_dir(p):
    return Path("~/.cache/honesty/pypi").expanduser() / p[:2] / (p[2:4] or "--") / p


# Given a list of simple index pages, taking the first as a baseline, record
# deletions given the mtime of the index page.
def main(files):
    paths = [Path(s) for s in sorted(files)]
    mdp = Path("data/deleted-metadata")
    assert mdp.exists()
    j = json.loads(DELETIONS_JSON_PATH.read_text())

    prev_observation = None
    prev_packages = set()
    for p in paths:
        ts = datetime.fromtimestamp(p.stat().st_mtime)
        ts = timezone("US/Pacific").localize(ts)
        data = p.read_text()
        # (cn, name)
        packages = set(LINK_RE.findall(data))
        print(len(packages))

        if prev_observation:
            lst = []
            j[ts.astimezone(timezone("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")] = lst

            deleted_packages = prev_packages - packages
            for d in deleted_packages:
                current_json = requests.get(LIVE_URL % d[1])
                if current_json.status_code in (200, 301):
                    # not deleted, just renamed, this is icky and I don't know
                    # how to trigger it.
                    print("NOT DELETED", d)
                    continue

                idx = cache_dir(d[0]) / "json"
                md = mdp / d[0]

                if idx.exists():
                    last_serial = json.loads(idx.read_text())["last_serial"]
                    md.mkdir(parents=True, exist_ok=True)
                    shutil.copy(idx, md / "json")
                else:
                    # See if hit.edu.cn has it
                    resp = requests.get(MIRROR_URL % d[1])
                    if resp.status_code == 200:
                        data = resp.text
                        last_serial = json.loads(data)["last_serial"]
                        md.mkdir(parents=True, exist_ok=True)
                        (md / "json").write_text(data)
                    else:
                        idx = cache_dir(d[0]) / "index.html"
                        if idx.exists():
                            m = SERIAL_RE.search(idx.read_text())
                            last_serial = int(m.group(1))
                            print("Missing json, but have index.html", d)
                        else:
                            print("Missing serial", d)
                            last_serial = None

                lst.append({"cn": d[0], "name": d[1], "last_serial": last_serial})

        prev_observation = ts
        prev_packages = packages

    DELETIONS_JSON_PATH.write_text(json.dumps(j, sort_keys=True, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
