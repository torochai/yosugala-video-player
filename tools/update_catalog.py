#!/usr/bin/env python3
"""カタログ（data/catalog.json）に、公式チャンネルの新しい動画を足す。計算で出せる値と案内ページ（s/）も作り直す。

使い方（player フォルダで）:
    python3 tools/update_catalog.py
    python3 tools/update_catalog.py --cookies-from-browser chrome   # YouTube にボット確認で止められたとき
    python3 tools/update_catalog.py --offline   # YouTube に接続しない（catalog.json を手で直したあと、計算で出す値を付け直す）

データは 2 つ:
- data/catalog.json: 元データ。曲・MC・MV（items）、公演（lives: 公演日・会場・セットリスト）、取り込みの決まり（import）。
  手で直すのはここだけ。直したら --offline で実行して、計算で出す値（下の DERIVED）と案内ページを作り直す
- data/youtube.json: YouTube から取った動画の情報（タイトル・長さ・公開日・チャプター・MV かどうか・サムネ）。このツールだけが書く

新しい動画（catalog.json にまだ 1 曲も入っていない動画）だけを足す。すでにある曲・MC には触らない（手で直した内容を消さない）:
- ライブ映像（単独の Official Live Video とフルライブ）。フルライブはチャプターで曲ごとに分ける（MC・SE などは除く）
- Official Music Video
- 曲名は import.aliases でそろえ、公演名は import.video_lives → import.live_rules → 動画タイトル の順で決める
- 新しい曲の ID は next_id から順に付ける（ID は一度付けたら変えない・使い回さない）
必要なもの: yt-dlp
"""
import json, os, re, subprocess, sys, time, datetime, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHANNEL = 'https://www.youtube.com/channel/UCP5_IRli-KbizrztKSmgh8Q'
# Official Music Video: 公式チャンネルの再生リスト「MusicVideo」の動画と、タイトルがちょうど「yosugala - 曲名」の動画
# （再生リストに入っていない新しい MV もあるため。メイキング・ティーザーなどはタイトルに【】「」などが付くので入らない）
MV_PLAYLIST = 'https://www.youtube.com/playlist?list=PLmu11HkWPvmbgMpfY4vZ7KVy67l7YyXJk'
MV_TITLE_RE = re.compile(r'^\s*yosugala\s*[-‐－–—]\s*[^【】\[\]「」『』()（）|｜]+$', re.I)
# 動画ごとの情報（概要欄）を取れたときは、概要欄に「- MusicVideo」の行がある動画を MV にする（再生リスト・タイトルより優先）。
# 新しい動画（ライブ映像でないもの）の概要欄を 1 回に MV_DESC_MAX 本まで確かめ、結果を youtube.json の desc_mv に覚えておく
MV_DESC_RE = re.compile(r'^\s*[-‐－–—]\s*music\s*video\s*$', re.I | re.M)
MV_DESC_MAX = 10
CHANNEL_ID = 'UCP5_IRli-KbizrztKSmgh8Q'
CACHE = os.path.join(ROOT, 'data', 'youtube.json')
OUT = os.path.join(ROOT, 'data', 'catalog.json')
OFFLINE = '--offline' in sys.argv[1:]
EXTRA = [a for a in sys.argv[1:] if a != '--offline']   # yt-dlp にそのまま渡す追加オプション（--cookies-from-browser など）

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


def title_date(title):
    m = re.search(r'(\d{4})\.(\d{1,2})\.(\d{1,2})', title)
    return f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}' if m else ''


def iso(upload_date):
    return f'{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}' if upload_date else ''


# 曲・MC の項目のうち、元データとして手で直すもの（この順で書く）と、finish() が計算で付け直すもの
SOURCE = ['id', 'title', 'vid', 'start', 'end', 'kind', 'type', 'live', 'chapter_start', 'chapter_end']
DERIVED = ['len', 'published', 'date', 'venue', 'no', 'duplicate_of']


def load_catalog():
    cat = load(OUT, {})
    cat.setdefault('lives', {}); cat.setdefault('items', []); cat.setdefault('import', {})
    cat.setdefault('next_id', max((x['id'] for x in cat['items']), default=0) + 1)
    return cat


def add_items(cat, new):
    """新しい曲・MC を足す（ID は next_id から。古い動画（公開日）順・動画の中では開始の早い順）。公演がなければ lives に足す"""
    for x in sorted(new, key=lambda x: (x.get('published') or '', x['vid'], x['start'])):
        x['id'] = cat['next_id']; cat['next_id'] += 1
        cat['items'].append(x)
        if x.get('live') and x['live'] not in cat['lives']:
            cat['lives'][x['live']] = {'date': x.get('date') or '', 'venue': ''}
    if new:
        ids = [x['id'] for x in cat['items'][-len(new):]]
        print(f'新しく足しました: {len(new)} 件（ID {ids[0]}' + (f'〜{ids[-1]}' if len(ids) > 1 else '') + '）')


def finish(cat, cache, offline=True):
    """計算で出せる値（DERIVED）を付け直し、並べ替えて catalog.json に書き、案内ページ（s/）を作り直す"""
    items, lives = cat['items'], cat['lives']
    for x in items:
        info = cache.get(x['vid'], {})
        x['published'] = iso(info.get('upload_date')) or x.get('published') or ''
        dur = info.get('duration') if info.get('duration') is not None else x.get('len')
        x['len'] = x['end'] - x['start'] if x.get('end') is not None else (dur - x['start'] if dur is not None else None)
        live = lives.get(x.get('live') or '', {})
        x['date'], x['venue'] = live.get('date', ''), live.get('venue', '')
    # 同じ公演・同じ曲の単独映像があるフルライブのチャプターには、その単独映像の動画 ID を duplicate_of に書く
    # （どちらもプレイヤーに表示する。公演の中の曲順で、単独映像をチャプターの位置に入れるのに使う）
    singles = {(x['live'], x['title']): x['vid'] for x in items if x['kind'] == 'single' and x.get('live')}
    for x in items:
        x.pop('duplicate_of', None)
        if x['kind'] == 'full' and (x.get('live'), x['title']) in singles:
            x['duplicate_of'] = singles[(x['live'], x['title'])]
    # 公演の中の曲順 no（1 から）
    #   フルライブのチャプター → 開始時刻の順。単独映像 → 同じ曲のチャプターの位置（チャプターのすぐあと）
    #   フルライブ映像がない公演 → lives のセットリスト（本編・アンコールの曲順）。どれでも分からなければ最後に公開日順
    for x in items:
        x.pop('no', None)
    for live in {x['live'] for x in items if x.get('live')}:
        group = [x for x in items if x.get('live') == live and x.get('type') != 'mc']   # MC には曲順を付けない
        chapter_at = {(x['duplicate_of'], x['title']): x['start'] for x in group if x.get('duplicate_of')}
        sl = lives.get(live, {})
        setlist = sl.get('main', []) + sl.get('encore', [])
        encore_video = set(sl.get('encore_video', []))   # 本編とアンコールの両方で披露し、映像はアンコールのほうの曲

        def pos(x):
            if x['kind'] == 'full':
                return (0, x['start'], 0)
            if (x['vid'], x['title']) in chapter_at:
                return (0, chapter_at[(x['vid'], x['title'])], 1)
            if x['title'] in setlist:
                i = len(setlist) - 1 - setlist[::-1].index(x['title']) if x['title'] in encore_video else setlist.index(x['title'])
                return (1, i, 0)
            return (2, 0, x['published'])
        for i, x in enumerate(sorted(group, key=pos)):
            x['no'] = i + 1
    # 曲名順（同じ曲の中は公演日の古い順。公演日が分からないものは公開日で比べる）。項目は SOURCE・DERIVED の順に
    items.sort(key=lambda s: (s['title'].casefold(), s['date'] or s['published']))
    cat['items'] = [{k: x[k] for k in SOURCE + DERIVED if k in x and x[k] is not None or k == 'end' and k in x} for x in items]
    out = {'updated': datetime.date.today().isoformat(), 'count': len(items), 'next_id': cat['next_id'],
           'lives': lives, 'items': cat['items'], 'import': cat['import']}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write('\n')
    names = sorted({s['title'] for s in items if s.get('type') != 'mc' and s['kind'] != 'mv'}, key=str.casefold)
    mc = sum(1 for x in items if x.get('type') == 'mc')
    mv = sum(1 for x in items if x['kind'] == 'mv')
    print(f'catalog.json を書きました: 全 {len(items)} 件（ライブ映像 {len(names)} 曲・MC {mc} 件・Music Video {mv} 本）')
    # 曲ごとの案内ページ（X で曲を共有したときのリンク先）もカタログに合わせて作り直す
    sys.path.insert(0, HERE); sys.dont_write_bytecode = True
    import make_song_pages
    make_song_pages.main(offline)


def main():
    cat = load_catalog()
    imp = cat['import']
    aliases = imp.get('aliases', {})
    exclude_videos = set(imp.get('exclude_videos', []))
    exclude_entries = set(imp.get('exclude_entries', []))
    live_rules = [(re.compile(p, re.I), name) for p, name in imp.get('live_rules', [])]
    video_lives = imp.get('video_lives', {})
    have = {x['vid'] for x in cat['items']}
    cache = load(CACHE, {})

    entries = []
    if OFFLINE:
        print('--offline: YouTube に接続せず、catalog.json の計算で出す値と案内ページだけを作り直します')
    else:
        print('公式チャンネルの動画一覧を取得中…')
        for tab in ('videos', 'streams'):
            try:
                d = ytdlp_json(['--flat-playlist', f'{CHANNEL}/{tab}'])
                entries += [e for e in (d.get('entries') or []) if e]
            except RuntimeError as e:
                if tab == 'videos':
                    sys.exit(f'動画一覧を取得できませんでした: {e}')
        # 「動画」と「ライブ」の両方の一覧に載っている動画は1本にまとめる（曲が二重に登録されないように）
        entries = list({e['id']: e for e in entries}.values())
        new = fetch_new(entries, cache, have, exclude_videos)
        add_items(cat, [x for x in build_items(new, cache, aliases, live_rules, video_lives)
                        if f'{x["vid"]}@{x["start"]}' not in exclude_entries])
    finish(cat, cache, OFFLINE)


def fetch_new(entries, cache, have, exclude_videos):
    """新しいライブ映像・Music Video を見つけ、動画の情報を youtube.json に取る。足す動画の [(動画ID, 'live' | 'mv')] を返す"""
    lives = [e for e in entries if LIVE_RE.search(e.get('title', '')) and e['id'] not in exclude_videos and not cache.get(e['id'], {}).get('mv')]
    print(f'ライブ映像: {len(lives)} 本（うちカタログにないもの: {sum(1 for e in lives if e["id"] not in have)} 本）')
    # Official Music Video: 再生リスト「MusicVideo」の動画と、タイトルがちょうど「yosugala - 曲名」の動画
    try:
        mvs = [e for e in (ytdlp_json(['--flat-playlist', MV_PLAYLIST]).get('entries') or []) if e]
    except RuntimeError as e:
        print(f'Music Video の一覧を取得できませんでした（前回の分を使います）: {e}')
        mvs = [{'id': vid, 'title': info['title']} for vid, info in cache.items() if info.get('mv')]
    mvs += [e for e in entries if MV_TITLE_RE.match(e.get('title') or '')]
    # 概要欄で確かめる: 新しい動画（ライブ映像・確かめ済みでないもの）の情報を 1 本ずつ取る。止められたら、残りは再生リスト・タイトルで判定する
    live_ids = {e['id'] for e in lives}
    todo = [e for e in entries if e['id'] not in cache and e['id'] not in live_ids and e['id'] not in exclude_videos][:MV_DESC_MAX]
    if todo:
        print(f'新しい動画の概要欄を確かめます（Music Video かどうか）: {len(todo)} 本')
    for e in todo:
        try:
            d = ytdlp_json([f'https://www.youtube.com/watch?v={e["id"]}'])
        except RuntimeError as err:
            print(f'  {e["id"]} の取得に失敗（残りは再生リスト・タイトルで判定します）: {err}')
            break
        is_mv = bool(MV_DESC_RE.search(d.get('description') or ''))
        cache[e['id']] = {'title': d.get('title', e.get('title', '')), 'duration': d.get('duration'), 'upload_date': d.get('upload_date'),
                          'chapters': [], 'desc_mv': is_mv}
        print(f'  {"Music Video" if is_mv else "MV ではない"}: {cache[e["id"]]["title"][:60]}')
        time.sleep(2)   # 連続アクセスを避ける
    mvs += [{'id': vid, 'title': info['title']} for vid, info in cache.items() if info.get('desc_mv')]
    mvs = list({e['id']: e for e in mvs}.values())
    # 概要欄を確かめて MV ではなかった動画は、再生リスト・タイトルに当てはまっても入れない
    mvs = [e for e in mvs if e['id'] not in exclude_videos and cache.get(e['id'], {}).get('desc_mv') is not False]
    print(f'Music Video: {len(mvs)} 本（うちカタログにないもの: {sum(1 for e in mvs if e["id"] not in have)} 本）')

    # Music Video はチャプターがいらないので、1本ずつ取得せず、再生リストのタイトル・長さと RSS の公開日で覚えておく
    # （1本ずつの取得は YouTube のボット確認で止められやすいため）
    new_mv = [e for e in mvs if e['id'] not in cache]
    if new_mv:
        # 公開日: 再生リストとチャンネルの RSS（どちらも新しい 15 本まで）から、日本時間の日付で
        pub = {}
        for feed in (f'playlist_id={MV_PLAYLIST.split("list=")[1]}', f'channel_id={CHANNEL_ID}'):
            try:
                with urllib.request.urlopen(f'https://www.youtube.com/feeds/videos.xml?{feed}', timeout=30) as r:
                    xml = r.read().decode('utf-8')
                for v, d in re.findall(r'<yt:videoId>([^<]+)</yt:videoId>.*?<published>([^<]+)</published>', xml, re.S):
                    t = datetime.datetime.fromisoformat(d.replace('Z', '+00:00')).astimezone(datetime.timezone(datetime.timedelta(hours=9)))
                    pub[v] = t.strftime('%Y%m%d')
            except Exception as err:
                print(f'  Music Video の公開日を取得できませんでした: {err}')
        for e in new_mv:
            cache[e['id']] = {'title': e.get('title', ''), 'duration': e.get('duration'), 'upload_date': pub.get(e['id']), 'chapters': [], 'mv': True}
            print(f'  取得（Music Video）: {cache[e["id"]]["title"][:60]}')
    for e in mvs:
        cache[e['id']]['mv'] = True

    for e in lives:
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
        save_cache(cache)
        time.sleep(2)   # 連続アクセスを避ける
    save_cache(cache)   # mv の印・概要欄の結果を付け足したときのため
    return [(e['id'], 'live') for e in lives if e['id'] not in have] + [(e['id'], 'mv') for e in mvs if e['id'] not in have]


def save_cache(cache):
    with open(CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


def build_items(new, cache, aliases, live_rules, video_lives):
    """新しい動画から曲の項目を作る（ライブ映像は単独映像 1 曲かチャプターごと、MV は 1 曲）"""
    out = []
    for vid, what in new:
        info = cache.get(vid)
        if not info:
            continue
        title, published = info['title'], iso(info.get('upload_date'))
        base = {'vid': vid, 'published': published, 'date': title_date(title)}
        if what == 'mv':
            # 曲名はタイトルの「yosugala - 曲名」から。概要欄で MV と分かった「【MV】yosugala「曲名」」のような形は「」の中を曲名に
            song = re.sub(r'^\s*yosugala\s*[-‐－–—]\s*', '', title, flags=re.I)
            song = re.sub(r'\s*[\[［(（【][^\]］)）】]*(mv|music video)[^\]］)）】]*[\]］)）】]\s*$', '', song, flags=re.I).strip()
            quoted = re.search(r'[「『]([^」』]+)[」』]', title)
            if not MV_TITLE_RE.match(title) and quoted:
                song = quoted.group(1).strip()
            out.append({**base, 'title': song, 'start': 0, 'end': None, 'kind': 'mv', 'live': '', 'date': ''})
            continue
        single = parse_single(title)
        if single and not (info['chapters'] and (info['duration'] or 0) > 1200):
            song, live = single
            out.append({**base, 'title': song, 'start': 0, 'end': None, 'kind': 'single',
                        'live': video_lives.get(vid) or live_by_rule(live_rules, title, live)})
        elif info['chapters']:
            live = video_lives.get(vid) or live_by_rule(live_rules, title, parse_full_live(title))
            for c in info['chapters']:
                name = c['title'].strip()
                if SKIP_CHAPTER_RE.match(name):
                    continue
                out.append({**base, 'title': name, 'start': int(c['start']), 'end': int(c['end']), 'kind': 'full', 'live': live})
        else:
            print(f'  曲に分けられない動画をスキップ: {title[:60]}')
    for x in out:
        x['title'] = aliases.get(x['title'], x['title'])
    return out


if __name__ == '__main__':
    main()
