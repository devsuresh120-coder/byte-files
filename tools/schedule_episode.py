"""Add one finished episode to queue/schedule.csv: the long video (by hand: YouTube, Facebook, TikTok) and its
3 Shorts (Buffer: YouTube Shorts, Facebook Reels, TikTok). Text comes from kits/epNNN.md and the episode timeline.

usage: python3 tools/schedule_episode.py <episode folder> <long date YYYY-MM-DD> <first short number> <short date 1> <short date 2> <short date 3>
e.g.   python3 tools/schedule_episode.py ep005_listening 2026-11-05 110 2026-11-06 2026-11-07 2026-11-08
Times (Sri Lanka, aimed at the European evening; owner 28 Oct 2026): long YouTube/Facebook 23:30, TikTok 23:45 (= 19:00 Berlin, scheduled ahead by hand); Shorts YouTube 22:30, Facebook 23:00, TikTok 23:30 (= 18:00 / 18:30 / 19:00 Berlin, via Buffer).
Rows already in the CSV (same episode + platform) are replaced. Files must already be on R2 (queue/r2.json)."""
import csv, json, os, re, sys, importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(ROOT, 'queue', 'schedule.csv')
FIELDS = ['episode', 'file', 'platform', 'due_at', 'title', 'text', 'comment', 'thumb', 'subs', 'tags']


def nl(s):
    return s.strip().replace('\r', '').replace('\n', '\\n')


def kit(n):
    k = open(os.path.join(ROOT, 'kits', f'ep{n:03d}.md'), encoding='utf-8').read()
    yt = k.split('## YouTube', 1)[1].split('\n## ', 1)[0]
    fb = k.split('## Facebook', 1)[1].split('\n## ', 1)[0]
    blocks = lambda s: re.findall(r'```[a-z]*\n(.*?)```', s, re.S)
    field = lambda s, name: (re.search(r'\*\*' + name + r':\*\*\s*(.+)', s) or [None, ''])[1].strip()
    out = dict(yt_title=field(yt, 'Title'), yt_desc=blocks(yt)[0], tags=field(yt, 'Tags'), pinned=field(yt, 'Pinned comment'),
               fb_title=field(fb, 'Title'), fb_text=blocks(fb)[0],
               fb_comment=(re.search(r'First comment:\s*(.+)', fb) or [None, ''])[1].strip())
    tt = k.split('## TikTok', 1)[1].split('\n## ', 1)[0] if '## TikTok' in k else ''
    out['tt_text'] = (blocks(tt) or [''])[0] if tt else ''
    return out


def shorts_of(folder):
    path = os.path.join(ROOT, 'studio', folder, 'script.py')
    spec = importlib.util.spec_from_file_location('s_' + folder, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    tl = json.load(open(os.path.join(ROOT, 'studio', folder, 'timeline.json')))
    out = []
    for r in m.SHORTS:
        sid, scene, a, b, head = (r[0], r[3], r[4], r[5], r[6]) if len(r) == 7 else r
        sc = next(s for s in tl['scenes'] if s['key'] == scene)
        caps = [s['cap'] for s in sc['sent'][a:b + 1]]
        out.append((sid, head, caps))
    return out


def tags_line(text, plat):
    tags = [t for t in re.findall(r'#\w+', text) if t.lower() not in ('#reels', '#shorts', '#tiktok')][:3]
    return ' '.join(tags + [{'youtube': '#Shorts', 'facebook': '#Reels', 'tiktok': '#TechTok'}[plat]])


def title_case(lines):
    t = ' '.join(lines).strip()
    if not t.isupper():
        return t
    t = t.lower()
    t = re.sub(r'(^|[.?!]\s+)([a-z])', lambda m: m.group(1) + m.group(2).upper(), t)
    for w in ('ftc', 'aws', 'dns', 'ai', 'y2k', 'npm', 'it', 'usb', 'cdn', 'tls', 'smtp'):
        t = re.sub(r'\b' + w + r'\b', w.upper(), t) if w != 'it' else t
    return t


def main(folder, long_date, first_short, sdates):
    n = int(re.search(r'ep(\d+)', folder).group(1))
    r2 = json.load(open(os.path.join(ROOT, 'queue', 'r2.json')))
    vid, thumb_key, subs = f'r2:{folder}/ep{n:03d}.mp4', None, f'r2:{folder}/ep{n:03d}_en.srt'
    for ext in ('jpg', 'png'):
        if f'r2:{folder}/ep{n:03d}_thumbnail.{ext}' in r2:
            thumb_key = f'r2:{folder}/ep{n:03d}_thumbnail.{ext}'
    for f in (vid, subs):
        if f not in r2:
            sys.exit(f'{f} is not on R2 yet (queue/r2.json)')
    K = kit(n)
    fb_body = K['fb_text'].strip()
    tt_text = K['tt_text'].strip() or (fb_body.split('\n\n')[0] + '\n\nWhole story on YouTube: The Byte Files (link in bio)\n\n'
                                      + ' '.join((re.findall(r'#\w+', fb_body) or [])[:4]) + ' #TechTok')
    rows = [
        dict(episode=n, file=vid, platform='youtube', due_at=f'{long_date} 23:30', title=K['yt_title'], text=nl(K['yt_desc']),
             comment=K['pinned'], thumb=thumb_key or '', subs=subs, tags=K['tags']),
        dict(episode=n, file=vid, platform='facebook', due_at=f'{long_date} 23:30', title=K['fb_title'], text=nl(fb_body),
             comment=K['fb_comment'], thumb=thumb_key or '', subs=subs, tags=''),
        dict(episode=n, file=vid, platform='tiktok', due_at=f'{long_date} 23:45', title=K['fb_title'], text=nl(tt_text),
             comment='', thumb=(f'r2:{folder}/ep{n:03d}_tiktok_cover.jpg' if f'r2:{folder}/ep{n:03d}_tiktok_cover.jpg' in r2 else thumb_key or ''),
             subs='', tags=''),
    ]
    ep_title = K['fb_title']
    for i, (sid, head, caps) in enumerate(shorts_of(folder)):
        num = first_short + i
        f = f'r2:{folder}/short{i + 1}.mp4'
        if f not in r2:
            sys.exit(f'{f} is not on R2 yet')
        lead = ' '.join(caps[:2])
        if len(lead) > 220:
            lead = caps[0]
        for plat, t in (('youtube', '22:30'), ('facebook', '23:00'), ('tiktok', '23:30')):
            more = f'Full story: {ep_title} on @thebytefilestv' if plat != 'tiktok' else 'Full story on YouTube: The Byte Files (link in bio)'
            text = f'{lead}\n\n{more}\n\n{tags_line(fb_body, plat)}'
            title = (title_case(head) + (' #Shorts' if plat == 'youtube' else ''))[:100]
            rows.append(dict(episode=num, file=f, platform=plat, due_at=f'{sdates[i]} {t}', title=title, text=nl(text),
                             comment='Which tech story should we explain next? 👇', thumb=(f'r2:{folder}/short{i + 1}_cover.jpg' if plat == 'facebook' else ''), subs='', tags=''))
    old = list(csv.DictReader(open(CSV, encoding='utf-8')))
    keys = {(str(r['episode']), r['platform']) for r in rows}
    keep = [r for r in old if (r['episode'], r['platform']) not in keys]
    with open(CSV, 'w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in keep + rows:
            w.writerow({k: r.get(k, '') for k in FIELDS})
    for r in rows:
        print(r['episode'], r['platform'], r['due_at'], r['title'][:60])


if __name__ == '__main__':
    a = sys.argv[1:]
    main(a[0], a[1], int(a[2]), a[3:6])
