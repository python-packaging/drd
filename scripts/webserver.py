from datetime import datetime
import json
import packaging.utils
from pathlib import Path

from flask import Flask, abort, make_response, render_template
app = Flask(__name__)

CACHE_LOCATION = Path("~/.cache/honesty").expanduser()

# We require a server restart to load new versions, unlike serving json.  Rethink.
DELETIONS_LOCATION = Path("data/deletions.json")
SERIALS_LOCATION = CACHE_LOCATION / "serials.json"

SERIALS = json.loads(SERIALS_LOCATION.read_text())
DELETIONS = json.loads(DELETIONS_LOCATION.read_text())

@app.route("/")
def main():
    return "DRD"

@app.route("/pypi/<project>/json")
def default_version_json(project):
    cn = packaging.utils.canonicalize_name(project)
    package_dir = CACHE_LOCATION / "pypi" / cn[:2] / (cn[2:4] or "--") / cn
    main_json_path = package_dir / "json"
    if not main_json_path.exists():
        abort(404)
    # TODO live pypi will redirect to the project name, not canonical name
    resp = make_response(main_json_path.read_text(), 200)
    resp.headers['Content-Type'] = 'application/json'
    return resp

@app.route("/simple/")
def simple_index():
    return "This space intentionally left blank"

@app.route("/simple/<project>/")
def simple_project(project):
    cn = packaging.utils.canonicalize_name(project)
    package_dir = CACHE_LOCATION / "pypi" / cn[:2] / (cn[2:4] or "--") / cn
    main_json_path = package_dir / "json"
    if not main_json_path.exists():
        abort(404)
    # TODO live pypi will redirect to the canonical name

    data = json.loads(main_json_path.read_text())

    return render_template("simple_project.html", data=data)

@app.route("/deletions/")
def deletions_index():
    data = []
    for k, items in DELETIONS['observed'].items():
        # TODO read json (either from cache, or repo) for items and give more
        # context + reasons from another file
        data.append(
            (
                datetime.strptime(k, "%Y-%m-%dT%H:%M:%SZ"),
                items
            )
        )
    data.sort(reverse=True)
    return render_template("deletion_index.html", data=data)

if __name__ == "__main__":
    app.run()
