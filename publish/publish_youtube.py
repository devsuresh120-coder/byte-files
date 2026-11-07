"""The Byte Files — long episodes → YouTube (GitHub Actions → YouTube Data API, no Buffer).

Takes the long-episode rows (episode < 100, platform "youtube") from queue/schedule.csv, downloads each video from its
public R2 link, uploads it as PRIVATE with a scheduled publish time (status.publishAt), then sets the thumbnail and the
English subtitles. YouTube makes the video public by itself at the due time.

Two jobs (env JOB): default = upload + schedule new episodes; JOB=live = check which scheduled videos are public now,
post the first comment, record them in queue/posted.json (which also releases the Shorts that wait for them).

Important: until Google approves the project's "API compliance audit", YouTube forces every API upload to PRIVATE and
ignores the schedule. The live job then notices ("needs Publish") and the dashboard tells the owner to press Publish in
YouTube Studio. After the audit, scheduling is fully automatic.

Quota (free): 10,000 units/day; upload 1600 + thumbnail 50 + subtitles 400 = 2050 per episode -> MAX_PER_RUN = 3.
Never marks anything as AI-generated.

Env: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN (GitHub secrets). Optional: DRY_RUN=1, CHECK_ONLY=1, ONLY_EPISODE=N.
"""
import csv, json, os, sys, tempfile, datetime as dt
import requests
import publish_long as L          # shared helpers: load/save/due_utc and the queue file paths

SCHEDULED = os.path.join(L.ROOT, "queue", "yt_scheduled.json")
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
DRY = os.environ.get("DRY_RUN") == "1"
CATEGORY = "28"           # Science & Technology
MAX_PER_RUN = 3
MIN_AHEAD_MIN = 15
CHUNK = 16 * 1024 * 1024  # multiple of 256 KiB


def env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        sys.exit(f"missing secret {name}")
    return v


def access_token():
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": env("YT_CLIENT_ID"), "client_secret": env("YT_CLIENT_SECRET"),
        "refresh_token": env("YT_REFRESH_TOKEN"), "grant_type": "refresh_token"}, timeout=60)
    if r.status_code != 200:
        sys.exit("Google sign-in failed: " + r.text[:300] + "  (a refresh token from an app still in 'Testing' expires after 7 days; publish the app 'In production')")
    return r.json()["access_token"]


def err(r):
    try:
        e = r.json()["error"]
        return f"{e.get('message')} [{e.get('code')}] {json.dumps(e.get('errors', [{}])[0].get('reason', ''))}"
    except Exception:
        return f"HTTP {r.status_code}: {r.text[:300]}"


def hdr(tok, **kw):
    return {"Authorization": f"Bearer {tok}", **kw}


def upload_video(tok, path, meta):
    size = os.path.getsize(path)
    r = requests.post(f"{UPLOAD}/videos?uploadType=resumable&part=snippet,status", headers=hdr(
        tok, **{"Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"}),
        data=json.dumps(meta), timeout=60)
    if r.status_code != 200:
        raise RuntimeError("could not start upload: " + err(r))
    url = r.headers["Location"]
    sent = 0
    with open(path, "rb") as f:
        while sent < size:
            chunk = f.read(CHUNK)
            end = sent + len(chunk) - 1
            for attempt in range(4):
                try:
                    r = requests.put(url, data=chunk, timeout=600, headers={"Content-Length": str(len(chunk)), "Content-Range": f"bytes {sent}-{end}/{size}"})
                    break
                except requests.RequestException as e:
                    if attempt == 3:
                        raise RuntimeError(f"upload interrupted: {e}")
            if r.status_code in (200, 201):
                return r.json()["id"]
            if r.status_code != 308:
                raise RuntimeError("upload failed: " + err(r))
            sent = end + 1
    raise RuntimeError("upload ended without a video id")


def set_thumbnail(tok, vid, url):
    img = requests.get(url, timeout=120); img.raise_for_status()
    mime = "image/png" if url.lower().endswith(".png") else "image/jpeg"
    r = requests.post(f"{UPLOAD}/thumbnails/set?videoId={vid}", headers=hdr(tok, **{"Content-Type": mime}), data=img.content, timeout=120)
    return None if r.status_code == 200 else err(r)


def add_subtitles(tok, vid, url, lang="en"):
    srt = requests.get(url, timeout=120); srt.raise_for_status()
    meta = json.dumps({"snippet": {"videoId": vid, "language": lang, "name": "English", "isDraft": False}})
    b = "bytefiles_boundary"
    body = (f"--{b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n--{b}\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + srt.content + f"\r\n--{b}--".encode()
    r = requests.post(f"{UPLOAD}/captions?uploadType=multipart&part=snippet", headers=hdr(tok, **{"Content-Type": f"multipart/related; boundary={b}"}), data=body, timeout=120)
    return None if r.status_code == 200 else err(r)


def first_comment(tok, vid, text):
    if not text:
        return None
    r = requests.post(f"{API}/commentThreads?part=snippet", headers=hdr(tok), timeout=60,
                      json={"snippet": {"videoId": vid, "topLevelComment": {"snippet": {"textOriginal": text}}}})
    return None if r.status_code == 200 else err(r)


def verify_scheduled(tok, posted, sched):
    now = dt.datetime.now(dt.timezone.utc)
    for key, v in list(sched.items()):
        if key in posted:
            del sched[key]; continue
        r = requests.get(f"{API}/videos", params={"part": "status", "id": v["video_id"]}, headers=hdr(tok), timeout=60)
        if r.status_code != 200 or not r.json().get("items"):
            print(f"  (could not check {key}: {err(r) if r.status_code != 200 else 'video not found'})"); continue
        st = r.json()["items"][0]["status"]
        due = dt.datetime.strptime(v["due_at"], "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=dt.timezone.utc)
        if st.get("privacyStatus") == "public":
            posted[key] = {"post_id": v["video_id"], "due_at": v["due_at"], "via": "youtube-api", "verified": True, "at": now.isoformat(timespec="seconds")}
            e = first_comment(tok, v["video_id"], v.get("comment", ""))
            if v.get("comment"):
                posted[key]["commented"] = e is None
                if e:
                    posted[key]["comment_error"] = e[:300]; print(f"::warning title=First comment failed ({key})::{e[:600]}")
            del sched[key]
            print(f"  {key} is public on YouTube -> posted.json")
        elif due < now - dt.timedelta(minutes=30):
            if not v.get("needs_publish"):
                v["needs_publish"] = True
                print(f"::warning title=Press Publish for ep {key}::YouTube kept it private (API audit not approved yet). Open YouTube Studio and publish video {v['video_id']}.")
        else:
            print(f"  {key} still scheduled for {v['due_at']}")


def main():
    if os.environ.get("GITHUB_EVENT_NAME") in ("push", "schedule") and (os.environ.get("YT_AUTO") != "1" or not os.environ.get("YT_REFRESH_TOKEN")):
        print("Automatic YouTube runs are OFF (set the repository variable YT_AUTO=1 once the secrets are in). Nothing done."); return
    if os.environ.get("CHECK_ONLY") == "1":
        tok = access_token()
        r = requests.get(f"{API}/channels", params={"part": "snippet", "mine": "true"}, headers=hdr(tok), timeout=60)
        items = r.json().get("items", []) if r.status_code == 200 else []
        if not items:
            sys.exit("YouTube check failed: " + (err(r) if r.status_code != 200 else "this token has no channel (pick the channel at the consent screen)"))
        print("YouTube channel OK:", items[0]["snippet"]["title"]); return
    posted, sched, r2 = L.load(L.POSTED, {}), L.load(SCHEDULED, {}), L.load(L.R2, {})
    if os.environ.get("JOB") == "live":
        tok = access_token()
        verify_scheduled(tok, posted, sched)
        L.save(L.POSTED, posted); L.save(SCHEDULED, sched); return
    rows = list(csv.DictReader(open(L.SCHEDULE, encoding="utf-8")))
    todo = []
    for r in rows:
        try:
            ep = int(r["episode"])
        except ValueError:
            continue
        key = f"{ep}:youtube"
        if r["platform"].lower() != "youtube" or ep >= L.LONG_BELOW or key in posted or key in sched or not r.get("due_at", "").strip():
            continue
        if os.environ.get("ONLY_EPISODE", "").strip() and str(ep) != os.environ["ONLY_EPISODE"].strip():
            continue
        todo.append(r)
    todo.sort(key=lambda r: L.due_utc(r["due_at"]))
    todo = todo[:MAX_PER_RUN]
    print(f"{len(todo)} long episode(s) to upload to YouTube (max {MAX_PER_RUN} per run: daily quota)")
    tok = None if DRY else access_token()
    failures = 0
    for r in todo:
        key = f"{r['episode']}:youtube"
        print(f"== {key}  due {r['due_at']} (Sri Lanka)")
        try:
            ref = r2.get(r["file"].strip())
            if not ref:
                raise RuntimeError(f"{r['file']} not in queue/r2.json")
            when = L.due_utc(r["due_at"])
            ahead = (when - dt.datetime.now(dt.timezone.utc)).total_seconds() / 60
            status = {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": False}
            if ahead >= MIN_AHEAD_MIN:
                status["publishAt"] = when.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            else:
                status["privacyStatus"] = "public"
            tags = [t.strip() for t in (r.get("tags") or "").split(",") if t.strip()][:30]
            meta = {"snippet": {"title": r["title"].strip()[:100], "description": r["text"].replace("\\n", "\n").strip()[:5000],
                                "tags": tags, "categoryId": CATEGORY, "defaultLanguage": "en", "defaultAudioLanguage": "en"}, "status": status}
            if DRY:
                print(f"  [dry] upload {ref['url']} as {status}; title={meta['snippet']['title']!r}; thumb={'yes' if r.get('thumb') else 'no'}; subs={'yes' if r.get('subs') else 'no'}"); continue
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "v.mp4")
                with requests.get(ref["url"], stream=True, timeout=300) as dl:
                    dl.raise_for_status()
                    with open(path, "wb") as f:
                        for c in dl.iter_content(1 << 20):
                            f.write(c)
                vid = upload_video(tok, path, meta)
            print(f"  uploaded: video {vid}")
            due_iso = when.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            sched[key] = {"video_id": vid, "due_at": due_iso, "comment": (r.get("comment") or "").replace("\\n", "\n").strip()}
            L.save(SCHEDULED, sched)
            cov, subs = r2.get((r.get("thumb") or "").strip()), r2.get((r.get("subs") or "").strip())
            for what, ref2, fn in (("thumbnail", cov, set_thumbnail), ("subtitles", subs, add_subtitles)):
                if ref2:
                    e = fn(tok, vid, ref2["url"])
                    print(f"  {what}: {'ok' if e is None else 'FAILED ' + e}")
                    if e:
                        print(f"::warning title=YouTube {what} failed (ep {r['episode']})::{e[:600]}")
        except Exception as e:
            failures += 1
            print(f"  FAILED: {str(e)[:500]}")
            print(f"::error title=YouTube upload failed (ep {r['episode']})::" + str(e).replace("\n", " ")[:900])
    print(f"done: {failures} failed")
    if failures:
        sys.exit(f"{failures} upload(s) failed; the others are recorded")


if __name__ == "__main__":
    main()
