"""Cut 9:16 Shorts / Reels from finished Byte Files episodes.

Layout (1080x1920): headline band on top, the episode picture (top 920 px of the 16:9 frame,
cropped to 1600 wide so the burned-in caption strip is left out) in the middle, big captions
from the episode timeline below it, and a "full episode" line at the bottom.

usage: python3 tools/make_shorts.py <out_dir>                 (the built-in list, ep 1-4)
       python3 tools/make_shorts.py <out_dir> ep005_listening ...  (only these episodes; rows come from each
       episode's script.py: SHORTS, and SHORTS_LOOK / SHORTS_NAME if set; video = studio/<ep>/epNNN.mp4)
"""
import sys as _s, os as _o
_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
import json, os, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(ROOT, 'studio', 'common', 'fonts')
OSWALD = os.path.join(FONTS, 'Oswald[wght].ttf')
SANS = os.path.join(FONTS, 'SourceSans3[wght].ttf')

EPNAME = {'ep001_crowdstrike': 'EP 1 · THE FILE THAT CRASHED THE WORLD', 'ep002_facebook': 'EP 2 · THE DAY FACEBOOK DISAPPEARED', 'ep003_xz': 'EP 3 · THE BACKDOOR ALMOST NOBODY SAW', 'ep004_aws': 'EP 4 · THE DAY HALF THE INTERNET STOPPED'}

LOOKS = {  # per-episode band colours (match each episode's own look)
    'ep001_crowdstrike': dict(bg=(11, 15, 26), ink=(234, 238, 245), acc=(239, 159, 39), mute=(132, 144, 166)),
    'ep002_facebook': dict(bg=(15, 16, 21), ink=(242, 238, 230), acc=(255, 214, 92), mute=(140, 140, 152)),
    'ep003_xz': dict(bg=(233, 225, 207), ink=(36, 32, 30), acc=(196, 44, 40), mute=(120, 112, 100)),
    'ep004_aws': dict(bg=(12, 38, 46), ink=(232, 238, 236), acc=(255, 140, 48), mute=(130, 162, 164)),
}

# (id, episode folder, video file, scene, first sentence, last sentence, headline lines)
SHORTS = [
    ('s1', 'ep001_crowdstrike', 'ep001.mp4', 'hook', 0, 9, ['8.5 MILLION COMPUTERS.', 'ONE FILE.']),
    ('s2', 'ep001_crowdstrike', 'ep001.mp4', 'bug', 0, 11, ['THE BUG THAT BROKE', 'THE WORLD: 20 ≠ 21']),
    ('s3', 'ep001_crowdstrike', 'ep001.mp4', 'fix', 0, 10, ['THE FIX? BY HAND.', 'ON EVERY COMPUTER.']),
    ('s1', 'ep002_facebook', 'ep002.mp4', 'hook', 0, 8, ['FACEBOOK VANISHED', 'FOR SIX HOURS']),
    ('s2', 'ep002_facebook', 'ep002.mp4', 'safety', 0, 8, ['THE SAFETY RULE THAT', 'MADE IT WORSE']),
    ('s3', 'ep002_facebook', 'ep002.mp4', 'locked', 1, 8, ['LOCKED OUT OF', 'THEIR OWN OFFICE']),
    ('s1', 'ep003_xz', 'ep003.mp4', 'hook', 0, 6, ['HALF A SECOND', 'EXPOSED A BACKDOOR']),
    ('s2', 'ep003_xz', 'ep003.mp4', 'pressure', 0, 6, ['THE TWO-YEAR', 'TRUST TRAP']),
    ('s3', 'ep003_xz', 'ep003.mp4', 'found', 0, 8, ['HOW ONE ENGINEER', 'CAUGHT IT']),
    ('s1', 'ep004_aws', 'ep004.mp4', 'hook', 0, 7, ['ONE EMPTY LINE.', '15 HOURS OF CHAOS.']),
    ('s2', 'ep004_aws', 'ep004.mp4', 'race', 1, 7, ['TWO ROBOTS,', 'ONE BLANK SIGN']),
    ('s3', 'ep004_aws', 'ep004.mp4', 'gridlock', 2, 8, ['FIXED? NOT', 'EVEN CLOSE.']),
]


def band(look, lines, out_png):
    W, H = 1080, 1920
    im = Image.new('RGB', (W, H), look['bg'])
    d = ImageDraw.Draw(im)
    f_tag = ImageFont.truetype(OSWALD, 40); f_tag.set_variation_by_name('Medium')
    f_head = ImageFont.truetype(OSWALD, 104); f_head.set_variation_by_name('SemiBold')
    f_foot = ImageFont.truetype(SANS, 44); f_foot.set_variation_by_name('SemiBold')
    d.text((W / 2, 130), 'THE BYTE FILES', font=f_tag, fill=look['mute'], anchor='mm')
    y = 260
    for i, ln in enumerate(lines):
        size = 104
        while f_head.getlength(ln) > W - 90 and size > 60:
            size -= 4
            f_head = ImageFont.truetype(OSWALD, size); f_head.set_variation_by_name('SemiBold')
        d.text((W / 2, y + i * 125), ln, font=f_head, fill=look['acc'] if i == len(lines) - 1 else look['ink'], anchor='mm')
    d.text((W / 2, 1640), EPNAME.get(look['name'], ''), font=f_tag, fill=look['mute'], anchor='mm')
    d.rounded_rectangle([60, 1720, W - 60, 1810], radius=45, outline=look['mute'], width=3)
    d.text((W / 2, 1765), 'Full story on @thebytefilestv', font=f_foot, fill=look['ink'], anchor='mm')
    im.save(out_png)


def ass_time(x):
    x = max(0.0, x)
    h = int(x // 3600); m = int(x % 3600 // 60); s = x % 60
    return f'{h}:{m:02d}:{s:05.2f}'


def captions(sents, t0, t1, out_ass, look):
    ink = look['ink'] if look['bg'][0] < 128 else (255, 255, 255)
    box = '&H50000000' if look['bg'][0] < 128 else '&H30241E20'
    col = '&H00%02X%02X%02X' % (ink[2], ink[1], ink[0])
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Source Sans 3 Bold Static,64,{col},{col},{box},{box},-1,0,0,0,100,100,0,0,3,18,0,8,70,70,1150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    for i, s in enumerate(sents):
        a = s['start'] - t0
        b = (sents[i + 1]['start'] - t0 - 0.02) if i + 1 < len(sents) else min(s['end'] + 0.4, t1) - t0
        ev.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Cap,,0,0,0,,{s['cap']}")
    open(out_ass, 'w').write(hdr + '\n'.join(ev) + '\n')


MASK = {}   # ep -> 'x=..:y=..:w=..:h=..:color=0xRRGGBB' box drawn over the crop (flat backgrounds only), e.g. a chapter tag
CROP = {}   # ep -> 'w:h:x:y' crop of the 16:9 frame (same 20:11 shape), e.g. to leave out a chapter tag top-left


def episode_rows(ep):
    """SHORTS rows + look + name declared in studio/<ep>/script.py"""
    import importlib.util, re as _re
    path = os.path.join(ROOT, 'studio', ep, 'script.py')
    spec = importlib.util.spec_from_file_location('ep_script_' + ep, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    n = int(_re.search(r'ep(\d+)', ep).group(1))
    vid = f'ep{n:03d}.mp4'
    if ep not in LOOKS:
        LOOKS[ep] = getattr(m, 'SHORTS_LOOK')
        if hasattr(m, 'SHORTS_CROP'):
            CROP[ep] = getattr(m, 'SHORTS_CROP')
        if hasattr(m, 'SHORTS_MASK'):
            MASK[ep] = getattr(m, 'SHORTS_MASK')
    if ep not in EPNAME:
        first = open(path).readline()
        t = _re.sub(r'^#\s*The Byte Files ep \d+:\s*', '', first).split('(')[0].strip().rstrip('.')
        EPNAME[ep] = getattr(m, 'SHORTS_NAME', f'EP {n} · {t.upper()}')
    rows = []
    for r in m.SHORTS:
        if len(r) == 7:
            rows.append(r)
        else:
            sid, scene, a, b, head = r
            rows.append((sid, ep, vid, scene, a, b, head))
    return rows


def main(out_dir, only=None):
    os.makedirs(out_dir, exist_ok=True)
    made = []
    rows = SHORTS if not only else [r for ep in only for r in episode_rows(ep)]
    for sid, ep, vid, scene, a, b, head in rows:
        tl = json.load(open(os.path.join(ROOT, 'studio', ep, 'timeline.json')))
        sc = next(s for s in tl['scenes'] if s['key'] == scene)
        sents = sc['sent'][a:b + 1]
        if scene == 'hook':
            title = next(s for s in tl['scenes'] if s['key'] == 'title')
            t0, t1 = 0.0, title['end']
        else:
            t0, t1 = max(0, sents[0]['start'] - 0.4), sents[-1]['end'] + 0.9
        look = dict(LOOKS[ep], name=ep)
        base = os.path.join(out_dir, f'{ep}_{sid}')
        band(look, head, base + '_bg.png')
        captions(sents, t0, t1, base + '.ass', look)
        src = os.path.join(ROOT, 'studio', ep, vid)
        if not os.path.exists(src):
            src = os.path.join(out_dir, '..', vid) if not os.path.exists(os.path.join(out_dir, vid)) else os.path.join(out_dir, vid)
        dur = t1 - t0
        mk = f",drawbox={MASK[ep]}:t=fill" if ep in MASK and scene != 'hook' else ''
        fc = (f"[0:v]crop={CROP.get(ep, '1600:880:160:0') if scene != 'hook' else '1600:880:160:0'}{mk},scale=1080:594[v];[1:v][v]overlay=0:520[o];"
              f"[o]subtitles={base}.ass:fontsdir={FONTS},fade=t=out:st={dur - 0.5:.2f}:d=0.5[out];"
              f"[0:a]afade=t=in:st=0:d=0.3,afade=t=out:st={dur - 0.6:.2f}:d=0.6[aout]")
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-ss', f'{t0:.2f}', '-t', f'{dur:.2f}', '-i', src,
                        '-loop', '1', '-t', f'{dur:.2f}', '-i', base + '_bg.png', '-filter_complex', fc,
                        '-map', '[out]', '-map', '[aout]', '-r', '30', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
                        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', base + '.mp4'], check=True)
        # Facebook uses the opening frame as the Reel cover and Buffer can't send a custom one: open on the cover frame
        import cover_first_frame
        cover_first_frame.main(base + '.mp4', base + '_c.mp4', base + '_cover.jpg'); os.replace(base + '_c.mp4', base + '.mp4')
        made.append((base + '.mp4', round(dur, 1), ' / '.join(head)))
        print(base + '.mp4', round(dur, 1))
    return made


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2:] or None)
