#!/usr/bin/env python

from datetime import datetime
import json
import os
import os.path
import sys
import xmlrpc.client
from pathlib import Path
from multiprocessing import Pool

from packaging.utils import canonicalize_name
import requests

PYPI_API_BASE = "https://pypi.org/pypi"
PYPI_BASE = "https://pypi.org/simple/"
CACHE_LOCATION = Path("~/.cache/honesty").expanduser()
SERIAL_LOCATION = CACHE_LOCATION / "serials"


def main(force=False):
    # TODO make force do something useful if today's serials already exist.
    date = datetime.utcnow().strftime("%Y%m%d_%H")
    SERIAL_LOCATION.mkdir(parents=True, exist_ok=True)
    existing_serials = sorted(SERIAL_LOCATION.glob("serials-*"))

    serial_path_today = SERIAL_LOCATION / f"serials-{date}"
    exists = serial_path_today.exists()
    if exists:
        return  # silently; we want this cron once a day

    fetch_serials(serial_path_today)
    if not existing_serials or force:
        update_cache(serial_path_today)
    else:
        update_cache_selective(serial_path_today, existing_serials[-1])


    if existing_serials:
        t = existing_serials[-1]
        record_deletions(serial_path_today, t)

    # Keep 30 days worth
    if len(existing_serials) > 30:
        for f in existing_serials[:-30]:
            f.unlink()


def fetch_serials(json_path: Path) -> None:
    client = xmlrpc.client.ServerProxy(PYPI_API_BASE)
    p = client.list_packages_with_serial()

    # If we fail during this, we don't want the json_path to exist, so fetch to
    # a temp file first.  In the live case the production cache is on a
    # loopback-mounted btrfs volume, and we want the tempfile to be on the same
    # mount so we can do an atomic rename.
    tmp = json_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(p, sort_keys=True, indent=2))
    tmp.rename(json_path)
    #TODO
    #(CACHE_LOCATION / "serials.json").symlink_to(json_path)


def record_deletions(today: Path, yesterday: Path):
    yesterday_json = json.loads(yesterday.read_text())
    today_json = json.loads(today.read_text())

    # The (non-canonical) name returned by list_packages_with_serial appears to
    # be able to change, and the json still redirects.  I believe these to be
    # the same package, but there's no id to confirm.
    # `fab_support` had serial 3865207 on 2019-12-08
    # `fab-support` had serial 6262934 on 2019-12-09
    # TODO symmetric_difference?
    today_json_cn = {
        canonicalize_name(x) for x in today_json
    }
    deletions = {
        x for x in yesterday_json if canonicalize_name(x) not in today_json_cn
    }
    #deletions = set(yesterday_json) - set(today_json)
    additions = set(today_json) - set(yesterday_json)
    for x in sorted(additions):
        print(f"+{x}")
    for x in sorted(deletions):
        print(f"-{x}")

    if not deletions:
        return

    deletions_path = Path("data/deletions.json")
    if deletions_path.exists():
        deletions_json = json.loads(deletions_path.read_text())
    else:
        deletions_json = {}
    deletions_json.setdefault("observed", {})

    lst = []
    today = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    for d in deletions:
        cn = canonicalize_name(d)
        lst.append({"name": d, "cn": cn, "last_serial": yesterday_json[d]})

        package_json = (cache_dir(cn) / "json").read_text()
        tmp = Path("data/deleted-metadata") / cn / "json"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(package_json)

    deletions_json['observed'][today] = lst

    deletions_path.write_text(json.dumps(deletions_json, sort_keys=True, indent=2))
    # TODO update some sort of friendly page merging in known reasons/links


def update_cache(today: Path) -> None:
    serials = json.loads(today.read_text())
    print(f"There are {len(serials)} packages today.")
    to_fetch = []
    for k, v in serials.items():
        cn = canonicalize_name(k)
        package_dir = cache_dir(cn)
        main_json_path = package_dir / "json"
        should_fetch = True
        if main_json_path.exists():
            serial = json.loads(main_json_path.read_text())["last_serial"]
            if serial == v:
                should_fetch = False

        if should_fetch:
            to_fetch.append((k, v, main_json_path))

    print(f"Need to fetch {len(to_fetch)} updates")
    # Right now the workload is fetch-heavy, but it may make sense to put the
    # json.loads above in the worker too.
    with Pool(10) as p:
        for result in p.imap_unordered(fetch_single, to_fetch):
            print(result)


def update_cache_selective(today: Path, yesterday: Path) -> None:
    serials_today = json.loads(today.read_text())
    print(f"There are {len(serials_today)} packages today.")
    serials_yesterday = json.loads(yesterday.read_text())

    to_fetch = []
    # Ones we need to update are either changed or new
    for k, v in serials_today.items():
        if serials_yesterday.get(k) != v:
            cn = canonicalize_name(k)
            package_dir = cache_dir(cn)
            main_json_path = package_dir / "json"
            to_fetch.append((k, v, main_json_path))

    print(f"Need to selective fetch {len(to_fetch)} updates")
    # Right now the workload is fetch-heavy, but it may make sense to put the
    # json.loads above in the worker too.
    with Pool(10) as p:
        for result in p.imap_unordered(fetch_single, to_fetch):
            print(result)


def fetch_single(args) -> None:
    (name, serial, where) = args

    where.parent.mkdir(parents=True, exist_ok=True)

    resp = requests.get(f"https://pypi.org/pypi/{name}/json")
    if resp.status_code == 404:
        # Packages with no releases do this; administrative bans don't
        # appear to trigger this path (because their serials just
        # disappear), but be wary about overwriting a useful cache
        # automatically.
        if where.exists():
            # If someone deletes all the releases, it 404's despite having a
            # known serial (from xmlrpc) and showing up in the simple index.
            # In this case we will overwrite something useful, and prefer to
            # keep the old version.  If this is later deleted, last_serial will
            # not match the last serial included in the deleted-metadata/ dir.
            tmp = json.loads(where.read_text())
            if 'releases' in tmp:
                return # don't overwrite with less useful info
        where.write_text(json.dumps({"last_serial": serial}))
        return f"{name} 404"
    assert resp.status_code == 200, resp.code
    where.write_text(resp.text)
    return f"{name} done"

    # TODO version-specific json too


def cache_dir(pkg_name: str) -> Path:
    cn = canonicalize_name(pkg_name)
    package_dir = CACHE_LOCATION / "pypi" / cn[:2] / (cn[2:4] or "--") / cn
    package_dir.mkdir(parents=True, exist_ok=True)
    return package_dir

if __name__ == "__main__":
    main("--force" in sys.argv)
