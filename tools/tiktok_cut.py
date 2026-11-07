"""TikTok cut of a long episode that is over 10 minutes (Buffer only takes TikTok videos up to 10 min).

Runs on GitHub Actions (the videos live on R2). Usage: python3 tools/tiktok_cut.py <episode number> <out dir>
- up to SPEED_MAX too long  -> one file epNNN_tiktok.mp4, video and voice sped up just enough (pitch kept)
- longer                    -> two parts epNNN_tiktok_p1.mp4 / _p2.mp4, split at the scene boundary nearest the middle,
                               with a small "PART 1 OF 2" / "PART 2 OF 2" tag for the first 4 seconds
Writes <out dir>/cut.json with what it did. The full episode on YouTube / Facebook is not touched.
"""
import csv, json, os, re, subprocess, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMIT = float(os.environ.get("CUT_LIMIT", "596"))   # target length, safely under Buffer's 10 minutes
SPEED_MAX = 1.04       # above this the voice starts to sound rushed: split instead
FONT = os.path.join(ROOT, "studio", "common", "fonts", "SourceSans3-BoldStatic.ttf")


def sh(*a):
    print("+", " ".join(a)[:300], flush=True)
    subprocess.run(a, check=True)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def enc(*extra):
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", *extra]


def tag(text):
    return (f"drawtext=fontfile={FONT}:text='{text}':x=w-tw-40:y=40:fontsize=h/22:fontcolor=white:"
            f"box=1:boxcolor=black@0.6:boxborderw=14:enable='lt(t,4)'")


def main():
    ep, out = int(sys.argv[1]), sys.argv[2]
    row = next(r for r in csv.DictReader(open(os.path.join(ROOT, "queue", "schedule.csv")))
               if r["platform"] == "tiktok" and int(r["episode"]) == ep)
    folder = re.search(r"r2:(ep\d{3}_[^/]+)/", row["file"]).group(1)
    r2 = json.load(open(os.path.join(ROOT, "queue", "r2.json")))
    src = os.path.join(out, "full.mp4")
    os.makedirs(out, exist_ok=True)
    full_key = f"r2:{folder}/ep{ep:03d}.mp4"
    print("downloading", r2[full_key]["url"], flush=True)
    sh("curl", "-sSfL", "--retry", "3", "-A", "byte-files-tiktok-cut", "-o", src, r2[full_key]["url"])   # r2.dev refuses Python's default agent
    d = duration(src)
    print(f"ep {ep}: {d:.1f} s", flush=True)
    info = {"episode": ep, "folder": folder, "seconds_full": round(d, 2), "files": []}
    if d <= LIMIT:
        info["mode"] = "none"
    elif d / LIMIT <= SPEED_MAX:
        f = d / LIMIT
        name = f"ep{ep:03d}_tiktok.mp4"
        sh("ffmpeg", "-y", "-loglevel", "error", "-i", src, "-filter_complex",
           f"[0:v]setpts=PTS/{f:.6f}[v];[0:a]atempo={f:.6f}[a]", "-map", "[v]", "-map", "[a]", *enc(), os.path.join(out, name))
        info.update(mode="speed", speed=round(f, 6), files=[{"name": name, "seconds": round(duration(os.path.join(out, name)), 2), "speed": round(f, 6)}])
    else:
        t = json.load(open(os.path.join(ROOT, "studio", folder, "timeline.json")))
        starts = [s["start"] for s in t["scenes"] if s["key"] not in ("hook", "title")]
        cut = min(starts, key=lambda s: abs(s - d / 2)) - 0.3      # just before the next scene's first word
        parts = [("p1", 0.0, cut, "PART 1 OF 2"), ("p2", cut, d, "PART 2 OF 2")]
        for p, a, b, label in parts:
            name = f"ep{ep:03d}_tiktok_{p}.mp4"
            f = max(1.0, (b - a) / LIMIT)
            vf = (f"setpts=PTS/{f:.6f}," if f > 1 else "") + tag(label)
            af = f"atempo={f:.6f}" if f > 1 else "anull"
            sh("ffmpeg", "-y", "-loglevel", "error", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", src,
               "-vf", vf, "-af", af, *enc(), os.path.join(out, name))
            info["files"].append({"name": name, "seconds": round(duration(os.path.join(out, name)), 2), "speed": round(f, 6),
                                  "part": p, "from": round(a, 2)})
        info["mode"] = "split"
    os.remove(src)
    json.dump(info, open(os.path.join(out, "cut.json"), "w"), indent=1)
    print(json.dumps(info, indent=1))
    for x in info["files"]:
        if x["seconds"] > 598:
            sys.exit(f"{x['name']} is still {x['seconds']} s")


if __name__ == "__main__":
    main()
