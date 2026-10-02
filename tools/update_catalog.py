#!/usr/bin/env python3
"""yosugala official の公式ライブ映像から、曲単位のカタログ（catalog.json）を作る。

使い方（player フォルダで）:
    python3 tools/update_catalog.py
    python3 tools/update_catalog.py --cookies-from-browser chrome   # YouTube にボット確認で止められたとき

- 公式チャンネルの動画一覧から、ライブ映像（単独の Official Live Video とフルライブ）を拾う
- フルライブはチャプターで曲ごとに分ける（MC・SE などは除く）
- 動画ごとの情報は tools/video_cache.json に保存し、次回からは新しい動画だけを取得する
- 曲名の表記ゆれ・除外・終了時刻の調整などは tools/catalog_overrides.json で直す
必要なもの: yt-dlp
"""
import json, os, re, subprocess, sys, time, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHANNEL = 'https://www.youtube.com/channel/UCP5_IRli-KbizrztKSmgh8Q'
CACHE = os.path.join(HERE, 'video_cache.json')
OVERRIDES = os.path.join(HERE, 'catalog_overrides.json')
OUT = os.path.join(ROOT, 'catalog.json')
EXTRA = sys.argv[1:]          # yt-dlp にそのまま渡す追加オプション（--cookies-from-browser など）

LIVE_RE = re.compile(r'live video|full live|【full】|oneman', re.I)
SKIP_CHAPTER_RE = re.compile(r'^(se|mc.*|.*\bmc\b.*|バンド紹介|ending.*|opening|オープニング|encore|アンコール|intro)$', re.I)


def ytdlp_json(args):
    r = subprocess.run(['yt-dlp', '--no-warnings', '-J', *EXTRA, *args], capture_output=True, text=True)
    if r.returncode != 0:
        msg = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'unknown error'
        raise RuntimeError(msg)
    return json.loads(r.stdout)


def load(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def clean_live(s):
    """「」『』や前後の - を外してライブ名を整える"""
    s = re.sub(r'^\s*yosugala\s*', '', s, flags=re.I)
    s = s.replace('「', ' ').replace('」', ' ').replace('『', ' ').replace('』', ' ')
    s = re.sub(r'\s+', ' ', s).strip(' -・/')
    return s


def parse_single(title):
    """'yosugala / 曲名 【Official Live Video】ライブ名' → (曲名, ライブ名)"""
    m = re.match(r'^\s*yosugala\s*/\s*(.+?)\s*【[^】]*live video[^】]*】\s*(.*)$', title, re.I)
    if not m:
        return None
    return m.group(1).strip(), clean_live(m.group(2))


def parse_full_live(title):
    t = re.sub(r'【[^】]*】', ' ', title)
    t = re.sub(r'\d{4}\.\d{1,2}\.\d{1,2}.*$', '', t)      # 日付以降（会場名など）は省く
    return clean_live(t)


def live_by_rule(rules, title, fallback):
    for pat, name in rules:
        if pat.search(title):
            return name
    return fallback


def date_from(title, upload_date):
    m = re.search(r'(\d{4})\.(\d{1,2})\.(\d{1,2})', title)
    if m:
        return f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    if upload_date:
        return f'{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}'
    return ''


def main():
    ov = load(OVERRIDES, {})
    aliases = ov.get('aliases', {})
    exclude_videos = set(ov.get('exclude_videos', []))
    exclude_entries = set(ov.get('exclude_entries', []))
    seg_fix = ov.get('segments', {})
    live_rules = [(re.compile(p, re.I), name) for p, name in ov.get('live_rules', [])]
    cache = load(CACHE, {})

    print('公式チャンネルの動画一覧を取得中…')
    entries = []
    for tab in ('videos', 'streams'):
        try:
            d = ytdlp_json(['--flat-playlist', f'{CHANNEL}/{tab}'])
            entries += [e for e in (d.get('entries') or []) if e]
        except RuntimeError as e:
            if tab == 'videos':
                sys.exit(f'動画一覧を取得できませんでした: {e}')
    lives = [e for e in entries if LIVE_RE.search(e.get('title', '')) and e['id'] not in exclude_videos]
    print(f'ライブ映像: {len(lives)} 本（うち新しく情報を取得するもの: {sum(1 for e in lives if e["id"] not in cache)} 本）')

    for i, e in enumerate(lives):
        vid = e['id']
        if vid in cache:
            continue
        try:
            d = ytdlp_json([f'https://www.youtube.com/watch?v={vid}'])
        except RuntimeError as err:
            print(f'  {vid} の取得に失敗: {err}')
            print('  YouTube のボット確認で止められた場合は --cookies-from-browser chrome を付けて再実行してください。')
            break
        cache[vid] = {
            'title': d.get('title', e.get('title', '')),
            'duration': d.get('duration'),
            'upload_date': d.get('upload_date'),
            'chapters': [{'title': c['title'], 'start': c['start_time'], 'end': c['end_time']} for c in (d.get('chapters') or [])],
        }
        print(f'  取得: {cache[vid]["title"][:60]}')
        with open(CACHE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=1)
        time.sleep(2)   # 連続アクセスを避ける

    songs = []
    for e in lives:
        vid = e['id']
        info = cache.get(vid)
        if not info:
            continue
        title, date = info['title'], date_from(info['title'], info.get('upload_date'))
        single = parse_single(title)
        if single and not (info['chapters'] and (info['duration'] or 0) > 1200):
            song, live = single
            songs.append({'song': song, 'vid': vid, 'start': 0, 'end': None, 'len': info['duration'],
                          'live': live_by_rule(live_rules, title, live), 'date': date, 'kind': 'single'})
        elif info['chapters']:
            live = live_by_rule(live_rules, title, parse_full_live(title))
            for c in info['chapters']:
                name = c['title'].strip()
                if SKIP_CHAPTER_RE.match(name):
                    continue
                start, end = int(c['start']), int(c['end'])
                songs.append({'song': name, 'vid': vid, 'start': start, 'end': end, 'len': end - start,
                              'live': live, 'date': date, 'kind': 'full'})
        else:
            print(f'  曲に分けられない動画をスキップ: {title[:60]}')

    out = []
    for s in songs:
        key = f'{s["vid"]}@{s["start"]}'
        if key in exclude_entries:
            continue
        s['song'] = aliases.get(s['song'], s['song'])
        if key in seg_fix:
            s.update(seg_fix[key])
            if s.get('end') is not None:
                s['len'] = s['end'] - s['start']
        out.append(s)
    out.sort(key=lambda s: (s['song'].casefold(), s['date']), reverse=False)

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'updated': datetime.date.today().isoformat(), 'count': len(out), 'songs': out},
                  f, ensure_ascii=False, indent=1)
    names = sorted({s['song'] for s in out}, key=str.casefold)
    print(f'catalog.json を更新しました: {len(out)} 件（{len(names)} 曲）')
    print('曲名一覧: ' + ' / '.join(names))


if __name__ == '__main__':
    main()
