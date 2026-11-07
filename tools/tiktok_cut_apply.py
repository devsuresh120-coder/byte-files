"""After tools/tiktok_cut.py + R2 upload: point the episode's TikTok row at the cut and record lengths in queue/r2.json.
usage: python3 tools/tiktok_cut_apply.py <cut.json> <r2 entries json>   (run on a fresh main checkout; idempotent)
Split episodes: the TikTok row becomes Part 1; Part 2 is a new row (episode 900 + N, sent like a Short via Buffer)
the next day at the same time."""
import csv, json, os, sys, datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHED, R2 = os.path.join(ROOT, "queue", "schedule.csv"), os.path.join(ROOT, "queue", "r2.json")
cut, new = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
ep, folder = cut["episode"], cut["folder"]
r2 = json.load(open(R2))
for x in cut["files"]:
    k = f"r2:{folder}/{x['name']}"
    r2[k] = {**new.get(k, r2.get(k, {})), "seconds": x["seconds"], "speed": x["speed"]}
json.dump(r2, open(R2, "w"), indent=1)
rows = list(csv.DictReader(open(SCHED, encoding="utf-8")))
fields = list(rows[0].keys())
row = next(r for r in rows if r["platform"] == "tiktok" and int(r["episode"]) == ep)
base_title = row["title"].replace(" (Part 1)", "")
if cut["mode"] == "speed":
    row["file"] = f"r2:{folder}/{cut['files'][0]['name']}"
elif cut["mode"] == "split":
    row["file"], row["title"] = f"r2:{folder}/ep{ep:03d}_tiktok_p1.mp4", base_title + " (Part 1)"
    p2 = f"{900 + ep}"
    due = (dt.datetime.strptime(row["due_at"], "%Y-%m-%d %H:%M") + dt.timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    two = {k: "" for k in fields}
    two.update(episode=p2, file=f"r2:{folder}/ep{ep:03d}_tiktok_p2.mp4", platform="tiktok", due_at=due,
               title=base_title + " (Part 2)", text=base_title + " (Part 2)\\n\\n" + row["text"])
    rows = [r for r in rows if not (r["episode"] == p2 and r["platform"] == "tiktok")] + [two]
w = csv.DictWriter(open(SCHED, "w", encoding="utf-8", newline=""), fieldnames=fields)
w.writeheader(); w.writerows(rows)
print(f"ep {ep}: {cut['mode']} -> TikTok rows updated")
