"""Make every listed Short open on its cover frame (Facebook's Reel cover), also the ones already waiting in Buffer.

queue/covers_todo.txt lists Short row numbers (one per line or ranges like 106-109). For each Short:
  1. download shortN.mp4 from R2, put its brightest frame (1.2-3.5 s) in front for 0.1 s (tools/cover_first_frame.py),
     upload it as shortN_v2.mp4 + shortN_cover.jpg and point every row of that Short to the new file;
  2. put the cover in the `thumb` column of the Facebook row (dashboard preview/download);
  3. if the Facebook post is already scheduled in Buffer (with the black-opening video), delete it there and drop it
     from queue/posted.json, so publish.py (run right after) re-creates it with the new video.
Buffer cannot send a custom cover (thumbnailUrl is refused), so the video's opening frame is the only way.
Posts that already went out are never touched. Runs in the "Short covers" workflow (R2 + Buffer secrets).
"""
import csv, io, json, os, subprocess, sys, tempfile
import requests
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "publish"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cover_first_frame import main as cover_first

TODO, SCHED, R2J, POSTED = "queue/covers_todo.txt", "queue/schedule.csv", "queue/r2.json", "queue/posted.json"
HEADER = "# Short row numbers that need a Facebook cover (e.g. 106-109). Emptied after each run.\n"


def note(t, m):
    print(f"::notice title={t}::" + str(m).replace("\n", " ")[:1500])


def wanted():
    eps = set()
    for ln in open(TODO) if os.path.exists(TODO) else []:
        ln = ln.split("#")[0].strip()
        if not ln:
            continue
        a, _, b = ln.partition("-")
        eps.update(range(int(a), int(b or a) + 1))
    return eps


def s3():
    import boto3
    return boto3.client("s3", endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
                        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
                        region_name="auto")


def delete_buffer_post(pid):
    import publish as P          # (reschedule.py runs on import, so its deletePost lookup is repeated here)
    st = P.gql('query($i:PostId!){ post(input:{id:$i}){ status } }', {"i": pid})["post"]["status"]
    if st != "scheduled":
        return f"status {st}: left alone"
    t = P.gql('query{ __type(name:"Mutation"){ fields{ name args{ name type{ name kind ofType{ name } } } } } }')["__type"]
    f = {x["name"]: x for x in t["fields"]}.get("deletePost")
    if not f:
        return "Buffer API has no deletePost: replace it by hand"
    arg = f["args"][0]; argname = arg["name"]; tname = arg["type"]["name"] or (arg["type"]["ofType"] or {}).get("name")
    fields = []
    if tname:
        it = P.gql('query($n:String!){ __type(name:$n){ inputFields{ name } } }', {"n": tname})["__type"]
        fields = [x["name"] for x in (it or {}).get("inputFields") or []]
    idfield = "id" if "id" in fields else (fields[0] if fields else None)
    q = ('mutation($i:PostId!){ deletePost(%s:{%s:$i}){ __typename ... on MutationError { message } } }' % (argname, idfield)) if idfield \
        else ('mutation($i:PostId!){ deletePost(%s:$i){ __typename ... on MutationError { message } } }' % argname)
    res = json.dumps(P.gql(q, {"i": pid}))
    return "deleted" if "MutationError" not in res else "error " + res


def main():
    eps = wanted()
    if not eps:
        print("covers_todo.txt is empty"); return
    text = open(SCHED, encoding="utf-8", newline="").read()
    rows = list(csv.DictReader(io.StringIO(text)))
    fields = list(rows[0].keys())
    r2 = json.load(open(R2J))
    posted = json.load(open(POSTED))
    client, bucket, base = s3(), os.environ["R2_BUCKET"], os.environ["R2_PUBLIC_URL"].rstrip("/")
    tmp = tempfile.mkdtemp()
    done = {}
    for r in rows:
        ep = int(r["episode"])
        if ep not in eps:
            continue
        ref = r["file"].strip()
        if ep not in done:
            if ref.endswith("_v2.mp4"):
                done[ep] = (ref, ref[:-7] + "_cover.jpg")
            else:
                mp4 = os.path.join(tmp, f"s{ep}.mp4"); new = os.path.join(tmp, f"s{ep}_v2.mp4"); jpg = os.path.join(tmp, f"s{ep}_cover.jpg")
                with requests.get(r2[ref]["url"], stream=True, timeout=300) as g:
                    g.raise_for_status()
                    with open(mp4, "wb") as f:
                        for chunk in g.iter_content(1 << 20): f.write(chunk)
                cover_first(mp4, new, jpg)
                vref, cref = ref[:-4] + "_v2.mp4", ref[:-4] + "_cover.jpg"
                for path, rr, ctype in ((new, vref, "video/mp4"), (jpg, cref, "image/jpeg")):
                    key = "byte-files/" + rr[3:]
                    client.upload_file(path, bucket, key, ExtraArgs={"ContentType": ctype})
                    r2[rr] = {"key": key, "url": f"{base}/{key}", "bytes": os.path.getsize(path)}
                done[ep] = (vref, cref)
                note(f"Short {ep}", f"{vref} opens on its cover frame")
        r["file"] = done[ep][0]
        if r["platform"].lower() == "facebook":
            r["thumb"] = done[ep][1]
            pk = f"{ep}:facebook"
            v = posted.get(pk)
            if v and v.get("via", "buffer") == "buffer" and v.get("post_id"):
                res = delete_buffer_post(v["post_id"])
                note(f"Buffer {pk}", res)
                if res == "deleted":
                    posted.pop(pk)
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=fields, lineterminator="\r\n" if "\r\n" in text else "\n")
    w.writeheader(); w.writerows(rows)
    open(SCHED, "w", encoding="utf-8", newline="").write(out.getvalue())
    json.dump(r2, open(R2J, "w"), indent=1)
    json.dump(posted, open(POSTED, "w"), indent=1)
    open(TODO, "w").write(HEADER)


main()
