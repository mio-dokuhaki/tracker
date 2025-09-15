import os, json, pathlib, requests, sys, datetime

repo = os.getenv("GITHUB_REPO")
issue = os.getenv("GITHUB_ISSUE")
webhook = os.getenv("DISCORD_WEBHOOK_URL")
state_path = os.getenv("STATE_PATH", ".state/state.json")
token = os.getenv("GITHUB_TOKEN", "")
if not (repo and issue and webhook):
    sys.exit(0)


def trunc(s, n):
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


p = pathlib.Path(state_path)
p.parent.mkdir(parents=True, exist_ok=True)
st = (
    json.loads(p.read_text())
    if p.exists()
    else {"sent_issue": False, "last_comment_id": 0}
)

h = {"Accept": "application/vnd.github+json"}
if token:
    h["Authorization"] = f"Bearer {token}"
api = f"https://api.github.com/repos/{repo}"
s = requests.Session()

r = s.get(f"{api}/issues/{issue}", headers=h, timeout=30)
r.raise_for_status()
iss = r.json()

if not st["sent_issue"]:
    author = (iss.get("user") or {}).get("login", "")
    author_url = f"https://github.com/{author}" if author else None
    author_icon = (iss.get("user") or {}).get("avatar_url", None)
    title = trunc(iss.get("title", ""), 256)
    url = iss.get("html_url")
    desc = trunc(iss.get("body", ""), 3500)
    ts = iss.get("created_at") or iss.get("updated_at")
    emb = {
        "title": f"Issue #{issue}: {title}",
        "url": url,
        "description": desc,
        "color": 0x5865F2,
        "timestamp": ts,
        "author": (
            {"name": author, "url": author_url, "icon_url": author_icon}
            if author
            else None
        ),
        "footer": {"text": repo},
    }
    requests.post(webhook, json={"embeds": [emb]}, timeout=30).raise_for_status()
    st["sent_issue"] = True
    p.write_text(json.dumps(st))

out = []
page = 1
while True:
    r = s.get(
        f"{api}/issues/{issue}/comments",
        headers=h,
        params={"per_page": 100, "page": page},
        timeout=30,
    )
    r.raise_for_status()
    d = r.json()
    if not d:
        break
    out += d
    if len(d) < 100:
        break
    page += 1

out.sort(key=lambda x: x.get("id", 0))
for c in [c for c in out if c.get("id", 0) > st["last_comment_id"]]:
    author = (c.get("user") or {}).get("login", "")
    author_url = f"https://github.com/{author}" if author else None
    author_icon = (c.get("user") or {}).get("avatar_url", None)
    url = (
        c.get("html_url")
        or f"https://github.com/{repo}/issues/{issue}#issuecomment-{c.get('id')}"
    )
    body = trunc(c.get("body", ""), 3500)
    ts = c.get("created_at") or c.get("updated_at")
    emb = {
        "title": f"New comment on #{issue}",
        "url": url,
        "description": body,
        "color": 0x57F287,
        "timestamp": ts,
        "author": (
            {"name": author, "url": author_url, "icon_url": author_icon}
            if author
            else None
        ),
        "footer": {"text": repo},
    }
    requests.post(webhook, json={"embeds": [emb]}, timeout=30).raise_for_status()
    st["last_comment_id"] = c.get("id", 0)
    p.write_text(json.dumps(st))
