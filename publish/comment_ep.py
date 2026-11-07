"""Post the planned first comment on an episode that was published by hand in YouTube Studio (no video id on record).
Reads queue/yt_comment_todo.txt (episode numbers), finds the video by its title in the channel's uploads, posts the
`comment` column of the episode's YouTube row, records it in queue/posted.json, empties the todo file."""
import csv, os, sys
import requests
import publish_long as L
import publish_youtube as Y


def say(m):
    print(m); print("::notice title=YouTube comment::" + m.replace("\n", " ")[:400])


def main():
    todo = os.path.join(L.ROOT, "queue", "yt_comment_todo.txt")
    eps = []
    for x in open(todo):
        x = x.split("#")[0].strip()
        if x:
            a, _, b = x.partition("-"); eps += range(int(a), int(b or a) + 1)
    if not eps:
        print("nothing to do"); return
    tok = Y.access_token()
    ch = requests.get(f"{Y.API}/channels", params={"part": "contentDetails", "mine": "true"}, headers=Y.hdr(tok), timeout=60).json()
    if "items" not in ch:
        sys.exit("channels call failed: " + str(ch)[:500])
    up = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    mine = ch["items"][0]["id"]
    vids, page = {}, None
    while True:
        j = requests.get(f"{Y.API}/playlistItems", params={"part": "snippet", "playlistId": up, "maxResults": 50, **({"pageToken": page} if page else {})}, headers=Y.hdr(tok), timeout=60).json()
        for it in j.get("items", []):
            vids[it["snippet"]["title"].strip()] = it["snippet"]["resourceId"]["videoId"]
        page = j.get("nextPageToken")
        if not page: break
    posted = L.load(L.POSTED, {})
    rows = list(csv.DictReader(open(L.SCHEDULE, encoding="utf-8")))
    def one(ep):
        r = next((x for x in rows if x["episode"] == str(ep) and x["platform"].lower() == "youtube"), None)
        if not r or not r["comment"].strip():
            say(f"ep {ep}: no YouTube row/comment text"); return
        vid = vids.get(r["title"].strip())
        if not vid:
            say(f"ep {ep}: not on the channel yet ({r['title'][:50]!r}), skipped"); return
        st = requests.get(f"{Y.API}/videos", params={"part": "status", "id": vid}, headers=Y.hdr(tok), timeout=60).json()["items"][0]["status"]
        if st.get("privacyStatus") != "public":
            say(f"ep {ep}: video {vid} is {st.get('privacyStatus')}, not public yet, skipped"); return
        ct = requests.get(f"{Y.API}/commentThreads", params={"part": "snippet", "videoId": vid, "maxResults": 100}, headers=Y.hdr(tok), timeout=60).json()
        if any((i["snippet"]["topLevelComment"]["snippet"].get("authorChannelId") or {}).get("value") == mine for i in ct.get("items", [])):
            say(f"ep {ep}: the channel already has a comment on {vid}, skipped"); return
        e = Y.first_comment(tok, vid, r["comment"])
        say(f"ep {ep} video {vid}: " + ("comment posted" if e is None else "FAILED " + e))
        if e is None:
            posted.setdefault(f"{ep}:youtube", {})["commented"] = True
            posted[f"{ep}:youtube"]["post_id"] = vid
    for ep in eps:
        try:
            one(ep)
        except Exception as ex:
            print(f"::warning title=Ep {ep} failed::{type(ex).__name__}: {str(ex)[:400]}")
    L.save(L.POSTED, posted)
    open(todo, "w").write("# episode numbers that need the first YouTube comment. Emptied after each run.\n")


try:
    main()
except SystemExit as ex:
    print("::error title=comment_ep stopped::" + str(ex.code)[:800]); raise
except BaseException as ex:
    import traceback
    print("::error title=comment_ep crashed::" + traceback.format_exc().replace("\n", " | ")[-900:]); raise
