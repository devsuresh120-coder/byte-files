"""The Byte Files — long episodes → TikTok (GitHub Actions → TikTok Content Posting API, no Buffer).

Takes the long-episode rows (episode < 100, platform "tiktok") from queue/schedule.csv. TikTok's API has no
"schedule for later" option, so this job runs hourly and posts a row once its due time (Sri Lanka time) has passed.
The video is downloaded from its public R2 link and sent to TikTok in chunks (FILE_UPLOAD, so no domain
verification is needed), then the job waits for TikTok to say PUBLISH_COMPLETE and records the post in
queue/posted.json ("<ep>:tiktok", same as tapping "Mark as posted").

Privacy: until TikTok approves the app's Content Posting audit, every API post is forced to SELF_ONLY (private to
the account owner). Keep TT_PRIVACY=SELF_ONLY until then, open the video in the TikTok app and switch it to
Everyone by hand (or after the audit set TT_PRIVACY=PUBLIC_TO_EVERYONE). Private posts are recorded with
"private": true so the dashboard can still show them.

Never marks anything as AI-generated (is_aigc is sent as false).

Env (GitHub secrets): TT_CLIENT_KEY, TT_CLIENT_SECRET. The refresh token comes from the 'TikTok sign-in' workflow and is kept\nencrypted (with TT_CLIENT_SECRET) in queue/tt_token.enc, updated whenever TikTok rotates it.
Optional: TT_PRIVACY (default SELF_ONLY), TT_AUTO (variable, =1 turns on the automatic runs), DRY_RUN=1,
CHECK_ONLY=1 (sign-in + account + limits check), ONLY_EPISODE=N, TEST_MODE=1 (upload one episode private, record nothing).
"""
import csv, json, os, sys, time, tempfile, datetime as dt
import requests
import publish_long as L          # shared helpers: load/save/due_utc and the queue file paths

API = "https://open.tiktokapis.com/v2"
DRY = os.environ.get("DRY_RUN") == "1"
TEST = os.environ.get("TEST_MODE") == "1"
INBOX = os.environ.get("TT_MODE", "").strip() == "inbox"   # send to the creator's TikTok inbox (draft) instead of Direct Post
MAX_PER_RUN = 2            # TikTok allows ~6 init calls/min and a daily cap per account; we only need 1-2 a day
CHUNK = 10 * 1024 * 1024   # 5-64 MB allowed per chunk; the last chunk may be bigger
POLL_SECONDS = 20
POLL_TRIES = 45            # ~15 min
LATE_GRACE_HOURS = 36      # a row that is older than this is not posted by accident after an outage; it is reported instead


def env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        sys.exit(f"missing secret {name}")
    return v


def err(r):
    try:
        j = r.json()
        e = j.get("error", j)
        return f"{e.get('message') or e.get('error_description') or r.text[:300]} [{e.get('code') or e.get('error')}] (HTTP {r.status_code})"
    except Exception:
        return f"HTTP {r.status_code}: {r.text[:300]}"


TOKEN_FILE = os.path.join(L.ROOT, "queue", "tt_token.enc")   # refresh token, encrypted with TT_CLIENT_SECRET


def _fernet():
    import base64, hashlib
    from cryptography.fernet import Fernet
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(env("TT_CLIENT_SECRET").encode()).digest()))


def load_refresh():
    if os.path.exists(TOKEN_FILE):
        return _fernet().decrypt(open(TOKEN_FILE, "rb").read().strip()).decode()
    return os.environ.get("TT_REFRESH_TOKEN", "").strip()


def save_refresh(tok):
    open(TOKEN_FILE, "wb").write(_fernet().encrypt(tok.encode()))


def has_token():
    return os.path.exists(TOKEN_FILE) or bool(os.environ.get("TT_REFRESH_TOKEN", "").strip())


def token_request(data):
    data = {"client_key": env("TT_CLIENT_KEY"), "client_secret": env("TT_CLIENT_SECRET"), **data}
    r = requests.post(f"{API}/oauth/token/", headers={"Content-Type": "application/x-www-form-urlencoded"}, data=data, timeout=60)
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200 or "access_token" not in j:
        raise RuntimeError(err(r))
    return j


def access_token():
    old = load_refresh()
    if not old:
        sys.exit("no TikTok sign-in yet: run the workflow 'TikTok sign-in' with the code from the authorize page")
    try:
        j = token_request({"grant_type": "refresh_token", "refresh_token": old})
    except RuntimeError as e:
        sys.exit(f"TikTok sign-in failed: {e}  (the refresh token lasts 365 days; if it expired or was revoked, sign in again with the 'TikTok sign-in' workflow)")
    new = j.get("refresh_token")
    if new and new != old:
        save_refresh(new)          # TikTok can rotate the refresh token: keep the newest one (committed encrypted)
        print("saved TikTok's new refresh token")
    return j["access_token"]


def hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8"}


def creator_info(tok):
    r = requests.post(f"{API}/post/publish/creator_info/query/", headers=hdr(tok), json={}, timeout=60)
    if r.status_code != 200 or r.json().get("error", {}).get("code") not in ("ok", None):
        raise RuntimeError("creator info failed: " + err(r))
    return r.json()["data"]


def check():
    tok = access_token()
    info = creator_info(tok)
    print(f"TikTok OK: @{info.get('creator_username')} ({info.get('creator_nickname')})")
    print("privacy options:", info.get("privacy_level_options"))
    print("max video length (s):", info.get("max_video_post_duration_sec"))
    print("comments disabled by account:", info.get("comment_disabled"), "| duet:", info.get("duet_disabled"), "| stitch:", info.get("stitch_disabled"))
    return info


def download(url, path):
    with requests.get(url, stream=True, timeout=300) as dl:
        dl.raise_for_status()
        with open(path, "wb") as f:
            for c in dl.iter_content(1 << 20):
                f.write(c)


def post_video(tok, info, row, ref):
    privacy = os.environ.get("TT_PRIVACY", "SELF_ONLY").strip() or "SELF_ONLY"
    if TEST:
        privacy = "SELF_ONLY"
    if not INBOX and privacy not in (info.get("privacy_level_options") or [privacy]):
        raise RuntimeError(f"account does not allow privacy level {privacy}: options are {info.get('privacy_level_options')}")
    caption = (row["title"].strip() + "\n\n" + row["text"].replace("\\n", "\n").strip()).strip()
    tags = " ".join("#" + t.strip().lstrip("#").replace(" ", "") for t in (row.get("tags") or "").split(",") if t.strip())
    if tags:
        caption += "\n" + tags
    caption = caption[:2200]
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "v.mp4")
        download(ref["url"], path)
        size = os.path.getsize(path)
        chunk = min(CHUNK, size)
        total = max(1, size // chunk)          # the last chunk absorbs the remainder
        body = {"post_info": {"title": caption, "privacy_level": privacy, "disable_comment": False, "disable_duet": False,
                              "disable_stitch": False, "video_cover_timestamp_ms": 1000, "is_aigc": False},
                "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": total}}
        if INBOX:      # draft upload: no caption/privacy here, the owner finishes the post in the TikTok app
            body = {"source_info": body["source_info"]}
            privacy = "INBOX"
        url = f"{API}/post/publish/inbox/video/init/" if INBOX else f"{API}/post/publish/video/init/"
        r = requests.post(url, headers=hdr(tok), json=body, timeout=60)
        j = r.json() if r.status_code < 500 else {}
        if r.status_code != 200 or j.get("error", {}).get("code") != "ok":
            e = err(r)
            if "unaudited_client_can_only_post_to_private_accounts" in e:
                e += "  (TikTok allows Direct Post from an unaudited app only to PRIVATE accounts: use inbox mode, or pass TikTok's audit)"
            raise RuntimeError("init failed: " + e)
        publish_id, upload_url = j["data"]["publish_id"], j["data"]["upload_url"]
        with open(path, "rb") as f:
            for i in range(total):
                start = i * chunk
                data = f.read(chunk if i < total - 1 else size - start)
                end = start + len(data) - 1
                for attempt in range(4):
                    try:
                        u = requests.put(upload_url, data=data, timeout=600, headers={
                            "Content-Type": "video/mp4", "Content-Length": str(len(data)), "Content-Range": f"bytes {start}-{end}/{size}"})
                        break
                    except requests.RequestException as e:
                        if attempt == 3:
                            raise RuntimeError(f"upload interrupted: {e}")
                        time.sleep(5)
                if u.status_code not in (200, 201, 206):
                    raise RuntimeError(f"chunk {i + 1}/{total} failed: HTTP {u.status_code} {u.text[:200]}")
    return publish_id, privacy


def wait_done(tok, publish_id):
    for _ in range(POLL_TRIES):
        r = requests.post(f"{API}/post/publish/status/fetch/", headers=hdr(tok), json={"publish_id": publish_id}, timeout=60)
        if r.status_code == 200:
            d = r.json().get("data", {})
            st = d.get("status")
            if st == "SEND_TO_USER_INBOX":
                return "PUBLISH_COMPLETE", None, None
            if st == "PUBLISH_COMPLETE":
                ids = d.get("publicaly_available_post_id") or d.get("publicly_available_post_id") or []
                return st, (ids[0] if ids else None), None
            if st == "FAILED":
                return st, None, d.get("fail_reason", "unknown")
            print(f"  status: {st}")
        time.sleep(POLL_SECONDS)
    return "TIMEOUT", None, "TikTok did not finish processing in time (it may still appear in the app)"


def main():
    if os.environ.get("GITHUB_EVENT_NAME") in ("push", "schedule") and (os.environ.get("TT_AUTO") != "1" or not has_token()):
        print("Automatic TikTok runs are OFF (set the repository variable TT_AUTO=1 once TikTok sign-in is done). Nothing done."); return
    if os.environ.get("CHECK_ONLY") == "1":
        check(); return
    if os.environ.get("STATUS_ID", "").strip():      # look up one publish_id (e.g. an inbox upload)
        tok = access_token()
        r = requests.post(f"{API}/post/publish/status/fetch/", headers=hdr(tok), json={"publish_id": os.environ["STATUS_ID"].strip()}, timeout=60)
        print(f"HTTP {r.status_code}: {r.text[:1000]}"); return
    posted, r2 = L.load(L.POSTED, {}), L.load(L.R2, {})
    rows = list(csv.DictReader(open(L.SCHEDULE, encoding="utf-8")))
    now = dt.datetime.now(dt.timezone.utc)
    todo = []
    for r in rows:
        try:
            ep = int(r["episode"])
        except ValueError:
            continue
        key = f"{ep}:tiktok"
        if r["platform"].lower() != "tiktok" or ep >= L.LONG_BELOW or not r.get("due_at", "").strip():
            continue
        if TEST:
            if str(ep) == os.environ.get("TEST_EPISODE", "5").strip():
                todo.append(r)
            continue
        if key in posted:
            continue
        if os.environ.get("ONLY_EPISODE", "").strip() and str(ep) != os.environ["ONLY_EPISODE"].strip():
            continue
        due = L.due_utc(r["due_at"])
        manual = bool(os.environ.get("ONLY_EPISODE", "").strip())      # "publish" for one episode ignores the due time
        if due > now and not manual:
            continue
        if now - due > dt.timedelta(hours=LATE_GRACE_HOURS) and not manual:
            print(f"  skip {key}: due {r['due_at']} is more than {LATE_GRACE_HOURS} h ago (post it by hand or run 'publish' for this episode)")
            continue
        todo.append(r)
    todo.sort(key=lambda r: L.due_utc(r["due_at"]))
    todo = todo[:MAX_PER_RUN]
    print(f"{len(todo)} long episode(s) due on TikTok")
    if not todo:
        return
    tok = None if DRY else access_token()
    info = None if DRY else creator_info(tok)
    if info:
        print(f"posting as @{info.get('creator_username')}; limit {info.get('max_video_post_duration_sec')} s")
    failures = 0
    for r in todo:
        key = f"{r['episode']}:tiktok"
        print(f"== {key}  due {r['due_at']} (Sri Lanka)")
        try:
            ref = r2.get(r["file"].strip())
            if not ref:
                raise RuntimeError(f"{r['file']} not in queue/r2.json")
            if DRY:
                print(f"  [dry] FILE_UPLOAD {ref['url']} ({ref.get('bytes')} bytes) privacy={os.environ.get('TT_PRIVACY', 'SELF_ONLY')}; caption starts {r['title'][:60]!r}"); continue
            pub_id, privacy = post_video(tok, info, r, ref)
            print(f"  sent to TikTok, publish_id {pub_id}; waiting for processing")
            st, post_id, why = wait_done(tok, pub_id)
            if st != "PUBLISH_COMPLETE":
                raise RuntimeError(f"TikTok status {st}: {why}")
            print(f"  done: {'in the TikTok inbox: open the TikTok app, tap the notification, paste the caption and Post' if INBOX else st}" + (f", post {post_id}" if post_id else ""))
            if TEST:
                print("  TEST: nothing recorded"); continue
            posted[key] = {"post_id": post_id or pub_id, "due_at": L.due_utc(r["due_at"]).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                           "via": "tiktok-api", "verified": True, "private": privacy != "PUBLIC_TO_EVERYONE", "inbox": INBOX,
                           "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
            L.save(L.POSTED, posted)
        except Exception as e:
            failures += 1
            print(f"  FAILED: {str(e)[:500]}")
            print(f"::error title=TikTok upload failed (ep {r['episode']})::" + str(e).replace("\n", " ")[:900])
    print(f"done: {failures} failed")
    if failures:
        sys.exit(f"{failures} upload(s) failed; the others are recorded")


if __name__ == "__main__":
    main()
