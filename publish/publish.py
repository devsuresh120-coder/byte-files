"""The Byte Files — Buffer publisher (GitHub Actions → Buffer): all Shorts, plus long episodes on TikTok.

Through Buffer: the Shorts / Reels (episode >= 100) and the long episodes' TikTok rows (episode < 100, platform tiktok;
cover frame = the title card, caption = title + text). Long episodes on Facebook / YouTube use their own APIs
(publish_long.py, publish_youtube.py). A long TikTok row whose time has already passed is never posted late.

Rules
- A Short is sent to Buffer only after its FULL episode is public on the same platform
  (its "<ep>:<platform>" key is in posted.json); TikTok Shorts wait for the episode on YouTube. The full episode = the folder in the Short's file
  (r2:ep001_crowdstrike/short1.mp4 → episode 1). Otherwise it waits; the next run tries again.
- Only the Buffer channels whose name contains BUFFER_CHANNEL_MATCH (default "byte") are used, so the
  Merge Conflict / Blobby channels in the same Buffer account are never touched. No match = stop.
- Files are already on R2: the public URL comes from queue/r2.json.
- Posts are created at most 6 days ahead (Buffer free plan: 10 queued posts per channel); a daily run tops up.
- Never marks anything as AI-generated.

Env: BUFFER_ACCESS_TOKEN (GitHub secret). Optional: DRY_RUN=1, BUFFER_CHANNEL_MATCH, LIST_ONLY=1.
"""
import csv, json, os, re, sys, time, datetime as dt
from zoneinfo import ZoneInfo
import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCHEDULE = os.path.join(ROOT, "queue", "schedule.csv")
POSTED = os.path.join(ROOT, "queue", "posted.json")
R2 = os.path.join(ROOT, "queue", "r2.json")
API = "https://api.buffer.com"
TZ = ZoneInfo("Asia/Colombo")            # due_at in schedule.csv is Sri Lanka time
DRY = os.environ.get("DRY_RUN") == "1"
MATCH = (os.environ.get("BUFFER_CHANNEL_MATCH") or "byte").lower()
YT_CATEGORY_SCIENCE_TECH = "28"
SHORTS_FROM = 100
HORIZON_DAYS = 6


class RateLimited(Exception):
    pass


def token():
    t = os.environ.get("BUFFER_ACCESS_TOKEN", "").strip()
    if not t:
        sys.exit("missing secret BUFFER_ACCESS_TOKEN")
    return t


def gql(query, variables=None):
    for _ in range(3):
        r = requests.post(API, json={"query": query, "variables": variables or {}},
                          headers={"Authorization": f"Bearer {token()}"}, timeout=60)
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", "60") or 60)
            print(f"  rate limited by Buffer; waiting {wait}s"); time.sleep(min(wait, 120)); continue
        r.raise_for_status()
        break
    else:
        raise RateLimited("Buffer rate limit (429) persists; the next run will continue")
    j = r.json()
    if j.get("errors"):
        raise RuntimeError(json.dumps(j["errors"], indent=1))
    return j["data"]


def all_channels():
    acc = gql("query { account { id organizations { id name } } }")["account"]
    out = []
    for org in acc["organizations"]:
        out += gql("query($o:OrganizationId!){ channels(input:{organizationId:$o}) { id name service } }",
                   {"o": org["id"]})["channels"]
    return out


def byte_channels():
    chans = all_channels()
    print("Buffer channels:", [(c["service"], c["name"]) for c in chans])
    picked = {}
    for c in chans:
        if MATCH in (c["name"] or "").lower().replace(" ", ""):
            picked.setdefault(c["service"].lower(), c)
    print(f"using (name contains '{MATCH}'):", {k: v["name"] for k, v in picked.items()})
    return picked


def due_iso(s):
    local = dt.datetime.strptime(s.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    return local.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def parent_episode(row):
    m = re.search(r"ep(\d{3})_", row.get("file", ""))
    return int(m.group(1)) if m else None


def _r2():
    return json.load(open(R2)) if os.path.exists(R2) else {}


def episode_seconds(row):
    ref = _r2().get(row.get("file", "").strip(), {})
    if ref.get("seconds"):
        return float(ref["seconds"])     # TikTok cuts record their real length
    m = re.search(r"r2:(ep\d{3}_[^/]+)/", row.get("file", ""))
    try:
        return float(json.load(open(os.path.join(ROOT, "studio", m.group(1), "timeline.json")))["total"])
    except Exception:
        return 0.0


TIKTOK_MAX_S = 598     # Buffer: "Video must be no longer than 10 minutes for TikTok"


def title_card_ms(row):
    """Long episode: the moment the title card is fully on screen (title scene start + 2.5 s), used as TikTok's cover frame."""
    m = re.search(r"r2:(ep\d{3}_[^/]+)/", row.get("file", ""))
    try:
        t = json.load(open(os.path.join(ROOT, "studio", m.group(1), "timeline.json")))
        sc = next(s for s in t["scenes"] if s["key"] == "title")
        speed = float(_r2().get(row.get("file", "").strip(), {}).get("speed") or 1)
        return int((sc["start"] + 2.5) * 1000 / speed)
    except Exception:
        return 1500


def build_input(row, channel_id, video_url, cover_url=None):
    text = row["text"].replace("\\n", "\n").strip()
    if int(row["episode"]) < SHORTS_FROM and row["platform"].lower() == "tiktok":   # long episode on TikTok: title on top
        text = (row["title"].strip() + "\n\n" + text).strip()[:2200]
    inp = {"channelId": channel_id, "text": text, "schedulingType": "automatic",
           "assets": [{"video": {"url": video_url, "metadata": {"thumbnailOffset": 1500}}}]}
    if int(row["episode"]) < SHORTS_FROM:
        inp["assets"][0]["video"]["metadata"]["thumbnailOffset"] = title_card_ms(row)
    # Buffer refuses thumbnailUrl ("social networks do not accept custom video thumbnail images", 2 Nov 2026) and
    # thumbnailOffset only works for Instagram/TikTok/Pinterest. Facebook takes the video's opening frame, so the
    # Short itself must open on a bright cover frame (tools/cover_first_frame.py).
    due = due_iso(row["due_at"])
    if due > dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"):
        inp.update(mode="customScheduled", dueAt=due)
    else:
        inp["mode"] = "addToQueue"            # its time already passed (e.g. waited for the full episode)
    p = row["platform"].lower()
    if p == "youtube":
        inp["metadata"] = {"youtube": {"title": row["title"].strip()[:100], "categoryId": YT_CATEGORY_SCIENCE_TECH,
                                       "privacy": "public", "madeForKids": False, "notifySubscribers": True,
                                       "isAiGenerated": False}}
    elif p == "tiktok":
        inp["metadata"] = {"tiktok": {"isAiGenerated": False}}
    elif p == "facebook":
        inp["metadata"] = {"facebook": {"type": "reel"}}
    return inp


CREATE = """mutation($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id text dueAt } }
    ... on MutationError { message }
  }
}"""


RETRY = set()   # keys re-sent after Buffer reported an error (kept as "retried" so we only retry once)


def check_buffer_errors(posted):
    """Posts Buffer accepted can still fail later (e.g. a YouTube upload timeout). Check recent ones: retry a failed post
    once (drop it from posted.json so it is created again); if it fails again, record the error so the dashboard shows it."""
    now_dt = dt.datetime.now(dt.timezone.utc)
    now, cutoff = (now_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z"), (now_dt - dt.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    changed = False
    for key, v in list(posted.items()):
        pid, due = v.get("post_id"), v.get("due_at") or ""
        if not pid or v.get("via") != "buffer" or not due or due > now or due < cutoff or v.get("verified"):
            continue
        try:
            p = gql('query($i:PostId!){ post(input:{id:$i}){ status error { message } } }', {"i": pid})["post"]
        except Exception as e:
            print(f"  (could not check Buffer post status for {key}: {str(e)[:200]})"); continue
        if p.get("status") == "sent":
            v["verified"] = True; v.pop("error", None); changed = True
        elif p.get("status") == "error":
            msg = ((p.get("error") or {}).get("message") or "unknown error").replace("\n", " ")
            if not v.get("retried"):
                print(f"::warning title=Buffer failed to publish {key}; sending it once more::{msg[:700]}")
                RETRY.add(key); del posted[key]; changed = True
            else:
                v["error"] = msg[:300]; changed = True
                print(f"::error title=Buffer failed again for {key}::{msg[:700]} Check the channel; post it by hand if it is not there.")
    if changed and not os.environ.get("DRY_RUN"):
        json.dump(posted, open(POSTED, "w"), indent=1)


def main():
    if os.environ.get("LIST_ONLY") == "1":
        byte_channels(); return
    posted = json.load(open(POSTED)) if os.path.exists(POSTED) else {}
    r2 = json.load(open(R2)) if os.path.exists(R2) else {}
    rows = list(csv.DictReader(open(SCHEDULE, encoding="utf-8")))
    check_buffer_errors(posted)
    horizon = (dt.datetime.now(TZ) + dt.timedelta(days=HORIZON_DAYS)).strftime("%Y-%m-%d %H:%M")
    todo, waiting = [], []
    only_long = os.environ.get("LONG_TIKTOK_EP", "").strip()     # test: send ONE long episode to TikTok via Buffer
    for r in rows:
        try:
            ep = int(r["episode"])
        except ValueError:
            continue
        key = f"{ep}:{r['platform'].lower()}"
        if only_long:
            if str(ep) == only_long and r["platform"].lower() == "tiktok" and key not in posted:
                todo.append(r)
            continue
        if key in posted or not r.get("due_at", "").strip() or r["due_at"].strip() > horizon:
            continue
        if ep < SHORTS_FROM:
            # long episodes: only TikTok goes through Buffer (Facebook/YouTube use their own APIs); never post a missed one late
            if r["platform"].lower() == "tiktok" and r["due_at"].strip() > dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M"):
                if episode_seconds(r) > TIKTOK_MAX_S:
                    print(f"::warning title=ep {ep} TikTok: over 10 min::Buffer only takes TikTok videos up to 10 minutes; post ep {ep} by hand or use a TikTok cut")
                    continue
                todo.append(r)
            continue
        par = parent_episode(r)
        # TikTok captions can't link anywhere, so a TikTok Short only needs its episode public on YouTube
        gate = "youtube" if r["platform"].lower() == "tiktok" else r["platform"].lower()
        if par is not None and f"{par}:{gate}" not in posted:
            waiting.append(f"{key} (waits for ep {par} on {gate})"); continue
        todo.append(r)
    if waiting:
        print("WAITING for the full episode to be marked posted:", waiting)
    todo.sort(key=lambda r: (r["due_at"].strip(), int(r["episode"])))   # soonest first: the free Buffer plan holds only 10 queued posts per channel
    print(f"{len(todo)} Short(s) to send to Buffer")
    if not todo:
        return
    chans = {} if DRY else byte_channels()
    failures = deferred = 0
    for r in todo:
        key = f"{r['episode']}:{r['platform'].lower()}"
        print(f"== {key}  due {r['due_at']} (Sri Lanka)")
        try:
            ref = r2.get(r["file"].strip())
            if not ref:
                raise RuntimeError(f"{r['file']} not in queue/r2.json")
            ch = chans.get(r["platform"].lower())
            if not DRY and not ch:
                raise RuntimeError(f"no Buffer {r['platform']} channel whose name contains '{MATCH}'")
            cov = r2.get((r.get("thumb") or "").strip())
            inp = build_input(r, ch["id"] if ch else "dry", ref["url"], cov["url"] if cov else None)
            if DRY:
                print("  [dry] createPost", json.dumps(inp, ensure_ascii=False)[:500]); continue
            res = gql(CREATE, {"input": inp})["createPost"]
            if "post" not in res:
                raise RuntimeError(res.get("message", "unknown Buffer error"))
            post = res["post"]
            posted[key] = {"post_id": post["id"], "due_at": post.get("dueAt"), "via": "buffer", 
                           "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **({"retried": True} if key in RETRY else {})}
            json.dump(posted, open(POSTED, "w"), indent=1)
            print(f"  ok: Buffer post {post['id']} due {post.get('dueAt')}")
            time.sleep(3)
        except RateLimited as e:
            print(f"  {e}"); break
        except Exception as e:
            msg = str(e)
            if re.search(r"limit|queue is full|upgrade|plan", msg, re.I):
                deferred += 1; print(f"  DEFERRED (Buffer plan limit, next run retries): {msg[:200]}"); print("::warning title=Buffer queue full (ep " + str(r["episode"]) + " " + r["platform"] + ")::" + msg.replace("\n", " ")[:600])
            else:
                failures += 1; print(f"  FAILED: {msg[:500]}"); print("::error title=Buffer publish failed (ep " + str(r["episode"]) + " " + r["platform"] + ")::" + msg.replace("\n", " ")[:900])
    if not DRY:
        json.dump(posted, open(POSTED, "w"), indent=1)
    print(f"done: {deferred} deferred, {failures} failed")
    if failures:
        sys.exit(f"{failures} Short(s) failed; the others are recorded in posted.json")


if __name__ == "__main__":
    main()
