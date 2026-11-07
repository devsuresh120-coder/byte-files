"""The Byte Files — long episodes → Facebook Page (GitHub Actions → Graph API, no Buffer).

Takes the long-episode rows (episode < 100, platform "facebook") from queue/schedule.csv and uploads each
video straight to the Page. Facebook fetches the video from its public R2 link, so nothing is downloaded here
except the small thumbnail.

How it works
- Due time is Sri Lanka time. More than 11 minutes ahead -> Facebook schedules it (published=false +
  scheduled_publish_time). Already due -> published right away.
- Rows due within HORIZON_DAYS (29) are uploaded and scheduled; later ones are picked up by the 3-hourly run.
- When a video goes live, the row's "comment" text is posted as the first comment from the Page (needs pages_manage_engagement).
- A scheduled video is first recorded in queue/fb_scheduled.json. Once Facebook reports it as published it moves to
  queue/posted.json ("<ep>:facebook", same as tapping "Mark as posted"), which releases the Shorts that wait for it.
- Never marks anything as AI-generated.

Two jobs (env JOB): default = schedule new posts; JOB=live = only check which scheduled videos went live and comment.
Env: FB_PAGE_ID, FB_PAGE_TOKEN (GitHub secrets). Optional: DRY_RUN=1, CHECK_ONLY=1 (token / Page check only).
"""
import csv, json, os, re, sys, datetime as dt
from zoneinfo import ZoneInfo
import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCHEDULE = os.path.join(ROOT, "queue", "schedule.csv")
POSTED = os.path.join(ROOT, "queue", "posted.json")
SCHEDULED = os.path.join(ROOT, "queue", "fb_scheduled.json")
R2 = os.path.join(ROOT, "queue", "r2.json")
GRAPH = "https://graph.facebook.com/v21.0"
GRAPH_VIDEO = "https://graph-video.facebook.com/v21.0"
TZ = ZoneInfo("Asia/Colombo")
DRY = os.environ.get("DRY_RUN") == "1"
LONG_BELOW = 100          # episode numbers >= 100 are Shorts (Buffer)
HORIZON_DAYS = 29         # Facebook schedules at most ~30 days ahead; the 3-hourly run tops up as later dates come into range
MIN_AHEAD_MIN = 11        # Facebook needs scheduled_publish_time at least 10 minutes ahead


def env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        sys.exit(f"missing secret {name}")
    return v


def load(path, default):
    return json.load(open(path)) if os.path.exists(path) else default


def save(path, data):
    json.dump(data, open(path, "w"), indent=1)


def graph_error(r):
    try:
        e = r.json().get("error", {})
    except Exception:
        return f"HTTP {r.status_code}: {r.text[:300]}"
    hint = ""
    if e.get("code") == 190:
        hint = " (token expired or invalid: create a new Page token and update FB_PAGE_TOKEN)"
    elif e.get("code") in (10, 200, 283):
        hint = " (missing permission: the token needs pages_manage_posts, pages_read_engagement and publish_video)"
    return f"{e.get('message', r.text[:300])} [code {e.get('code')}/{e.get('error_subcode')}]{hint}"


def check_page():
    pid, tok = env("FB_PAGE_ID"), env("FB_PAGE_TOKEN")
    r = requests.get(f"{GRAPH}/{pid}", params={"fields": "id,name,fan_count", "access_token": tok}, timeout=60)
    if r.status_code != 200:
        sys.exit("Page check failed: " + graph_error(r))
    j = r.json()
    print(f"Page OK: {j.get('name')} (id {j.get('id')}), followers: {j.get('fan_count')}")
    r = requests.get(f"{GRAPH}/me/permissions", params={"access_token": tok}, timeout=60)
    if r.status_code == 200:
        print("permissions:", sorted(p["permission"] for p in r.json().get("data", []) if p.get("status") == "granted") or "(none listed: normal for a Page token)")


def due_utc(s):
    return dt.datetime.strptime(s.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=TZ).astimezone(dt.timezone.utc)


def verify_scheduled(posted, sched):
    """Move scheduled videos that Facebook has now published into posted.json."""
    tok = env("FB_PAGE_TOKEN")
    for key, v in list(sched.items()):
        if key in posted:
            del sched[key]; continue
        r = requests.get(f"{GRAPH}/{v['video_id']}", params={"fields": "published,scheduled_publish_time", "access_token": tok}, timeout=60)
        if r.status_code != 200:
            print(f"  (could not check {key}: {graph_error(r)})"); continue
        if r.json().get("published"):
            posted[key] = {"post_id": v["video_id"], "due_at": v["due_at"], "via": "facebook-api", "verified": True,
                           "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
            err = first_comment(v["video_id"], v.get("comment", ""))
            if v.get("comment"):
                posted[key]["commented"] = err is None
                if err:
                    posted[key]["comment_error"] = err[:300]
                    print(f"::warning title=First comment failed ({key})::{err[:600]}")
            del sched[key]
            print(f"  {key} is now public on the Page -> posted.json")
        else:
            print(f"  {key} still scheduled for {v['due_at']}")


def first_comment(video_id, text):
    """Comment as the Page on the live video. Returns None on success or an error message."""
    if not text:
        return None
    r = requests.post(f"{GRAPH}/{video_id}/comments", data={"message": text, "access_token": env("FB_PAGE_TOKEN")}, timeout=60)
    return None if r.status_code == 200 else graph_error(r)


TEST = os.environ.get("TEST_MODE") == "1"


def upload(row, r2):
    pid, tok = env("FB_PAGE_ID"), env("FB_PAGE_TOKEN")
    ref = r2.get(row["file"].strip())
    if not ref:
        raise RuntimeError(f"{row['file']} not in queue/r2.json")
    when = due_utc(row["due_at"])
    ahead = (when - dt.datetime.now(dt.timezone.utc)).total_seconds() / 60
    data = {"access_token": tok, "file_url": ref["url"], "title": row["title"].strip()[:255],
            "description": row["text"].replace("\\n", "\n").strip()}
    if TEST:
        data["published"] = "false"      # unpublished: only Page admins can see it (Meta Business Suite -> Content)
        mode = "TEST: uploaded unpublished (not public, not scheduled)"
    elif ahead >= MIN_AHEAD_MIN:
        data.update(published="false", scheduled_publish_time=int(when.timestamp()))
        mode = f"scheduled for {when.isoformat()}"
    else:
        data["published"] = "true"
        mode = "publish now (its time has passed)"
    files = None
    cov = r2.get((row.get("thumb") or "").strip())
    if cov and DRY:
        files = {"thumb": None}     # dry run: don't download the thumbnail
    elif cov:
        t = requests.get(cov["url"], timeout=120); t.raise_for_status()
        mime = "image/png" if cov["url"].lower().endswith(".png") else "image/jpeg"
        files = {"thumb": (os.path.basename(cov["url"]), t.content, mime)}
    if DRY:
        print(f"  [dry] POST /{pid}/videos {mode}; title={data['title']!r}; video={ref['url']}; thumb={'yes' if files else 'no'}")
        return None, when
    r = requests.post(f"{GRAPH_VIDEO}/{pid}/videos", data=data, files=files, timeout=900)
    if r.status_code != 200:
        raise RuntimeError(graph_error(r))
    vid = r.json().get("id")
    print(f"  ok: Facebook video {vid} {mode}")
    return vid, when


def main():
    if os.environ.get("GITHUB_EVENT_NAME") in ("push", "schedule") and os.environ.get("FB_AUTO") != "1":
        print("Automatic runs are OFF (set the repository variable FB_AUTO=1 to turn them on). Nothing done."); return
    if TEST:
        ep = os.environ.get("TEST_EPISODE", "5").strip()
        rows = [r for r in csv.DictReader(open(SCHEDULE, encoding="utf-8")) if r["episode"] == ep and r["platform"].lower() == "facebook"]
        if not rows:
            sys.exit(f"no Facebook row for episode {ep}")
        print(f"TEST upload of episode {ep}; nothing is recorded in posted.json")
        upload(rows[0], load(R2, {})); return
    if os.environ.get("CHECK_ONLY") == "1":
        check_page(); return
    posted, sched, r2 = load(POSTED, {}), load(SCHEDULED, {}), load(R2, {})
    rows = list(csv.DictReader(open(SCHEDULE, encoding="utf-8")))
    if os.environ.get("JOB") == "live":      # live job: only check what went live, post the first comment, record it
        verify_scheduled(posted, sched)
        save(POSTED, posted); save(SCHEDULED, sched)
        return
    horizon = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=HORIZON_DAYS)
    todo = []
    for r in rows:
        try:
            ep = int(r["episode"])
        except ValueError:
            continue
        key = f"{ep}:facebook"
        if r["platform"].lower() != "facebook" or ep >= LONG_BELOW or key in posted or key in sched:
            continue
        if os.environ.get("ONLY_EPISODE", "").strip() and str(ep) != os.environ["ONLY_EPISODE"].strip():
            continue
        if not r.get("due_at", "").strip() or due_utc(r["due_at"]) > horizon:
            continue
        todo.append(r)
    todo.sort(key=lambda r: due_utc(r["due_at"]))
    print(f"{len(todo)} long episode(s) to send to Facebook")
    failures = 0
    for r in todo:
        key = f"{r['episode']}:facebook"
        print(f"== {key}  due {r['due_at']} (Sri Lanka)")
        try:
            vid, when = upload(r, r2)
            if DRY:
                continue
            due_iso = when.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            comment = (r.get("comment") or "").replace("\\n", "\n").strip()
            if when <= dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=MIN_AHEAD_MIN):
                posted[key] = {"post_id": vid, "due_at": due_iso, "via": "facebook-api",
                               "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
                err = first_comment(vid, comment)
                if comment:
                    posted[key]["commented"] = err is None
                    if err:
                        posted[key]["comment_error"] = err[:300]
            else:
                sched[key] = {"video_id": vid, "due_at": due_iso, "comment": comment}
            save(POSTED, posted); save(SCHEDULED, sched)
        except Exception as e:
            failures += 1
            print(f"  FAILED: {str(e)[:500]}")
            print(f"::error title=Facebook upload failed (ep {r['episode']})::" + str(e).replace("\n", " ")[:900])
    print(f"done: {failures} failed")
    if failures:
        sys.exit(f"{failures} upload(s) failed; the others are recorded")


if __name__ == "__main__":
    main()
