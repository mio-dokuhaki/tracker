import os, sys, json, pathlib, time, requests, datetime

repo = os.getenv("GITHUB_REPO")
issue = os.getenv("GITHUB_ISSUE")
webhook = os.getenv("DISCORD_WEBHOOK_URL")
state_path = os.getenv("STATE_PATH", ".state/state.json")
token = os.getenv("GITHUB_TOKEN", "")
if not (repo and issue and webhook):
    sys.exit(0)


def now_iso():
    return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()


def trunc(s, n):
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def atomic_write(p, data):
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(p)


p = pathlib.Path(state_path)
p.parent.mkdir(parents=True, exist_ok=True)
st = (
    json.loads(p.read_text())
    if p.exists()
    else {
        "sent_issue": False,
        "last_comment_id": 0,
        "seen_comment_ids": [],
        "issue_etag": None,
        "comments_etag": None,
        "last_comments_check": "1970-01-01T00:00:00+00:00",
    }
)

s = requests.Session()
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

retry = Retry(
    total=6,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"],
)
s.mount("https://", HTTPAdapter(max_retries=retry))

h = {"Accept": "application/vnd.github+json"}
if token:
    h["Authorization"] = f"Bearer {token}"
api = f"https://api.github.com/repos/{repo}"

ih = dict(h)
if st.get("issue_etag"):
    ih["If-None-Match"] = st["issue_etag"]
r = s.get(f"{api}/issues/{issue}", headers=ih, timeout=30)
if r.status_code == 304:
    pass
else:
    r.raise_for_status()
    iss = r.json()
    if not st["sent_issue"]:
        author = (iss.get("user") or {}).get("login", "")
        title = trunc(iss.get("title", ""), 256)
        url = iss.get("html_url")
        desc = trunc(iss.get("body", ""), 3500)
        ts = iss.get("created_at") or iss.get("updated_at") or now_iso()
        emb = {
            "title": f"Issue #{issue}: {title}",
            "url": url,
            "description": desc,
            "color": 0x5865F2,
            "timestamp": ts,
            "author": {"name": author} if author else None,
            "footer": {"text": repo},
        }
        s.post(webhook, json={"embeds": [emb]}, timeout=30).raise_for_status()
        st["sent_issue"] = True
    et = r.headers.get("ETag")
    if et:
        st["issue_etag"] = et
    atomic_write(p, st)

ch = dict(h)
if st.get("comments_etag"):
    ch["If-None-Match"] = st["comments_etag"]
params = {"per_page": 100}
since = st.get("last_comments_check")
if since:
    params["since"] = since
page = 1
all_comments = []
while True:
    rp = s.get(
        f"{api}/issues/{issue}/comments",
        headers=ch,
        params={**params, "page": page},
        timeout=30,
    )
    if rp.status_code == 304:
        break
    rp.raise_for_status()
    data = rp.json()
    if not data:
        break
    all_comments += data
    if len(data) < 100:
        break
    page += 1

if all_comments:
    all_comments.sort(key=lambda x: x.get("id", 0))
    seen = set(st.get("seen_comment_ids", []))
    new = [
        c
        for c in all_comments
        if c.get("id", 0) > st.get("last_comment_id", 0) and c.get("id") not in seen
    ]
    for c in new:
        author = (c.get("user") or {}).get("login", "")
        url = c.get("html_url")
        body = trunc(c.get("body", ""), 3500)
        ts = c.get("created_at") or c.get("updated_at") or now_iso()
        emb = {
            "title": f"New comment on #{issue}",
            "url": url,
            "description": body,
            "color": 0x57F287,
            "timestamp": ts,
            "author": {"name": author} if author else None,
            "footer": {"text": repo},
        }
        s.post(webhook, json={"embeds": [emb]}, timeout=30).raise_for_status()
        st["last_comment_id"] = max(st["last_comment_id"], c.get("id", 0))
        seen.add(c.get("id"))
        atomic_write(p, st)
        time.sleep(1.2)
    st["seen_comment_ids"] = list(seen)[-5000:]
et2 = locals().get("rp", None).headers.get("ETag") if locals().get("rp", None) else None
if et2:
    st["comments_etag"] = et2
st["last_comments_check"] = now_iso()
atomic_write(p, st)
