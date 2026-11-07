"""Review sheet: the opening frame (t=0, what Facebook shows as the Reel cover) of the listed Shorts.
usage (in the "Short frames" workflow): python tools/first_frames.py 106-151 -> review/first_frames.png"""
import json, os, subprocess, sys, tempfile, csv
import requests
from PIL import Image, ImageDraw, ImageStat
a, _, b = sys.argv[1].partition("-"); eps = range(int(a), int(b or a) + 1)
r2 = json.load(open("queue/r2.json")); tmp = tempfile.mkdtemp(); tiles = []
rows = {int(r["episode"]): r for r in csv.DictReader(open("queue/schedule.csv", encoding="utf-8")) if r["platform"] == "facebook"}
for e in eps:
    r = rows.get(e)
    if not r: continue
    url = r2[r["file"].strip()]["url"]; mp4 = f"{tmp}/{e}.mp4"
    open(mp4, "wb").write(requests.get(url, timeout=300).content)
    for t in (0.0, 1.5):
        jpg = f"{tmp}/{e}_{t}.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", mp4, "-frames:v", "1", "-vf", "scale=180:-1", jpg], check=True)
        im = Image.open(jpg).convert("RGB"); d = ImageDraw.Draw(im)
        lum = ImageStat.Stat(im.convert("L")).mean[0]
        d.rectangle((0, 0, 180, 22), fill=(0, 0, 0)); d.text((4, 4), f"{e} t={t} lum={lum:.0f}", fill=(255, 255, 0))
        tiles.append(im)
    print(e, r["file"])
W, H = tiles[0].size; cols = 12; rws = (len(tiles) + cols - 1) // cols
sheet = Image.new("RGB", (W * cols, H * rws), (40, 40, 40))
for i, im in enumerate(tiles): sheet.paste(im, ((i % cols) * W, (i // cols) * H))
os.makedirs("review", exist_ok=True); sheet.save("review/first_frames.png", optimize=True)
