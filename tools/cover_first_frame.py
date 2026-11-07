"""Make a Short open on its cover frame, so Facebook's Reel cover is never black.

Buffer cannot send a custom cover to Facebook (thumbnailUrl is refused, thumbnailOffset is not supported there), and
Facebook takes the Reel's opening frame. So the brightest frame between 1.2 s and 3.5 s (headline + picture +
caption) is put in front of the video for 0.1 s (3 frames: invisible to viewers, but it is what Facebook shows).
usage: cover_first_frame.py in.mp4 out.mp4 [cover.jpg]   (cover.jpg is also written, for the dashboard)
"""
import json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from short_covers import best_frame

HOLD = 0.1


def probe(mp4):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,sample_rate,r_frame_rate",
                          "-of", "json", mp4], capture_output=True, text=True, check=True).stdout
    st = json.loads(out)["streams"]
    v = next(s for s in st if s["codec_type"] == "video"); a = next((s for s in st if s["codec_type"] == "audio"), None)
    n, d = v["r_frame_rate"].split("/")
    return int(v["width"]), int(v["height"]), round(int(n) / int(d)), int(a["sample_rate"]) if a else None


def main(src, dst, cover=None):
    cover = cover or dst[:-4] + "_cover.jpg"
    best_frame(src, cover)
    w, h, fps, sr = probe(src)
    sr = sr or 48000
    fc = (f"[0:v]scale={w}:{h},setsar=1,fps={fps},format=yuv420p[c];[2:v]setsar=1,fps={fps},format=yuv420p[v];"
          f"[1:a]aresample={sr}[s];[2:a]aresample={sr}[a];[c][s][v][a]concat=n=2:v=1:a=1[ov][oa]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", str(fps), "-t", str(HOLD), "-i", cover,
                    "-f", "lavfi", "-t", str(HOLD), "-i", f"anullsrc=r={sr}:cl=stereo", "-i", src,
                    "-filter_complex", fc, "-map", "[ov]", "-map", "[oa]", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", dst], check=True)
    return cover


if __name__ == "__main__":
    print(main(*sys.argv[1:]))
