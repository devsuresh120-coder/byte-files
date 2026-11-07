"""Make a Facebook/Reel cover jpg for every Short in a folder: the brightest frame between 1.2 s and 3.5 s
(captions + picture visible, never the black fade-in). Writes <short>_cover.jpg next to each mp4.
usage: short_covers.py <dir with epNNN_slug_sN.mp4>"""
import glob, os, subprocess, sys
from PIL import Image, ImageStat


def best_frame(mp4, out):
    best = None
    for i, t in enumerate([1.2 + 0.3 * k for k in range(8)]):
        tmp = f'{out}.t{i}.jpg'
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-ss', f'{t:.2f}', '-i', mp4, '-frames:v', '1', '-q:v', '2', tmp], check=True)
        lum = ImageStat.Stat(Image.open(tmp).convert('L')).mean[0]
        if best is None or lum > best[0]:
            best = (lum, tmp)
    os.replace(best[1], out)
    for f in glob.glob(f'{out}.t*.jpg'):
        os.remove(f)
    return best[0]


if __name__ == '__main__':
    for mp4 in sorted(glob.glob(os.path.join(sys.argv[1], '*_s[0-9].mp4'))):
        out = mp4[:-4] + '_cover.jpg'
        print(os.path.basename(out), round(best_frame(mp4, out), 1))
