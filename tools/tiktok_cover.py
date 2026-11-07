"""Vertical 9:16 TikTok cover (1080x1920) for a long episode, built from its 16:9 thumbnail.

TikTok crops covers to 9:16 (and the profile grid to about 3:4), so the wide thumbnail loses its sides.
This puts the whole thumbnail in the middle, the episode title above it and a "full episode" line below,
all inside the 3:4 centre (y 240–1680) so nothing is cut on the profile grid either.

usage: python3 tools/tiktok_cover.py <episode folder> [<thumbnail path>]  ->  studio/<folder>/epNNN_tiktok_cover.jpg
"""
import glob, os, re, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(ROOT, 'studio', 'common', 'fonts')


def font(name, size, var):
    f = ImageFont.truetype(os.path.join(FONTS, name), size)
    f.set_variation_by_name(var)
    return f


def wrap(text, f, maxw):
    words, lines, cur = text.split(), [], ''
    for w in words:
        t = (cur + ' ' + w).strip()
        if f.getlength(t) <= maxw:
            cur = t
        else:
            lines.append(cur); cur = w
    return lines + [cur]


def title_of(n):
    k = os.path.join(ROOT, 'kits', f'ep{n:03d}.md')
    if os.path.exists(k):
        txt = open(k, encoding='utf-8').read()
        fb = txt.split('## Facebook', 1)[1] if '## Facebook' in txt else ''
        m = re.search(r'\*\*Title:\*\*[ \t]*([^\n]+)', fb) or re.search(r'^# Episode \d+\s*[—-]\s*([^\n(]+)', txt, re.M)
        if m:
            return m.group(1).strip()
    first = open(os.path.join(ROOT, 'studio', glob.glob(os.path.join(ROOT, 'studio', f'ep{n:03d}_*'))[0].split('/')[-1], 'script.py')).readline()
    return re.sub(r'^#\s*The Byte Files ep \d+:\s*', '', first).split('(')[0].strip()


def main(folder, thumb=None):
    n = int(re.search(r'ep(\d+)', folder).group(1))
    if not thumb:
        cands = glob.glob(os.path.join(ROOT, 'studio', folder, f'ep{n:03d}_thumbnail.*')) + glob.glob(os.path.join(ROOT, 'thumbnails', f'ep{n:03d}.*'))
        thumb = cands[0]
    th = Image.open(thumb).convert('RGB')
    W, H = 1080, 1920
    # background: the thumbnail itself, blurred and darkened, so the colours match the episode
    bg = th.resize((int(H * th.width / th.height), H)).crop((0, 0, W, H)) if th.width / th.height > W / H else th.resize((W, H))
    bg = bg.filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, Image.new('RGB', (W, H), (8, 10, 16)), 0.62)
    im = bg.copy()
    d = ImageDraw.Draw(im)
    tw = 1000
    t = th.resize((tw, int(tw * th.height / th.width)), Image.LANCZOS)
    ty = 980 - t.height // 2
    shadow = Image.new('RGBA', (tw + 40, t.height + 40), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([20, 20, tw + 20, t.height + 20], radius=26, fill=(0, 0, 0, 170))
    im.paste(shadow.filter(ImageFilter.GaussianBlur(14)), ((W - tw) // 2 - 20, ty - 10), shadow.filter(ImageFilter.GaussianBlur(14)))
    mask = Image.new('L', t.size, 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, t.width - 1, t.height - 1], radius=22, fill=255)
    im.paste(t, ((W - tw) // 2, ty), mask)
    # title above
    f_tag = font('Oswald[wght].ttf', 44, 'Medium')
    title = title_of(n).upper()
    size = 92
    f_t = font('Oswald[wght].ttf', size, 'SemiBold')
    lines = wrap(title, f_t, W - 120)
    while len(lines) > 3 and size > 60:
        size -= 6; f_t = font('Oswald[wght].ttf', size, 'SemiBold'); lines = wrap(title, f_t, W - 120)
    # balance the lines (no single word left alone on the last line): same line count, narrowest width that still fits
    if len(lines) > 1:
        lo, hi, nlines = 200, W - 120, len(lines)
        while hi - lo > 4:
            mid = (lo + hi) // 2
            if len(wrap(title, f_t, mid)) <= nlines:
                hi = mid
            else:
                lo = mid
        lines = wrap(title, f_t, hi)
    y0 = ty - 60 - len(lines) * int(size * 1.12)
    for i, ln in enumerate(lines):
        d.text((W / 2, y0 + i * int(size * 1.12)), ln, font=f_t, fill=(245, 246, 250), anchor='mt')
    d.text((W / 2, min(330, y0 - 45)), f'THE BYTE FILES · EP {n}', font=f_tag, fill=(239, 180, 80), anchor='mm')   # always above the title, however many lines it has
    # pill below
    f_p = font('SourceSans3[wght].ttf', 50, 'Bold')
    py = ty + t.height + 90
    label = 'FULL EPISODE'
    pw = f_p.getlength(label) + 90
    d.rounded_rectangle([(W - pw) / 2, py, (W + pw) / 2, py + 96], radius=48, fill=(239, 159, 39))
    d.text((W / 2, py + 48), label, font=f_p, fill=(15, 17, 24), anchor='mm')
    out = os.path.join(ROOT, 'studio', folder, f'ep{n:03d}_tiktok_cover.jpg')
    im.save(out, quality=90)
    print(out)
    return out


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
