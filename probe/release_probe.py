# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
import json


def _login(value):
    return value.get("login") if isinstance(value, dict) else None


def _summarise(url):
    try:
        text = gl.nondet.web.render(url, mode="text")
    except Exception as error:
        return json.dumps({"error": "fetch failed", "detail": str(error)[:200]})
    try:
        data = json.loads(text)
    except Exception:
        return json.dumps({"error": "not json", "length": len(text), "head": text[:200]})
    items = data if isinstance(data, list) else [data]
    out = []
    for release in items[:5]:
        if not isinstance(release, dict):
            continue
        assets = release.get("assets") if isinstance(release.get("assets"), list) else []
        out.append({
            "tag": release.get("tag_name"),
            "published_at": release.get("published_at"),
            "author": _login(release.get("author")),
            "draft": release.get("draft"),
            "prerelease": release.get("prerelease"),
            "assets": [
                {
                    "name": asset.get("name"),
                    "size": asset.get("size"),
                    "state": asset.get("state"),
                    "uploader": _login(asset.get("uploader")),
                    "digest": asset.get("digest"),
                }
                for asset in assets[:5]
                if isinstance(asset, dict)
            ],
        })
    return json.dumps({"ok": True, "length": len(text), "releases": out}, sort_keys=True)


class ReleaseProbe(gl.Contract):
    last: str

    def __init__(self):
        self.last = ""

    @gl.public.write
    def probe(self, url: str) -> str:
        result = gl.eq_principle.strict_eq(lambda: _summarise(url))
        self.last = result
        return result

    @gl.public.view
    def get_last(self) -> str:
        return self.last
