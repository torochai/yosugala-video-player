#!/usr/bin/env python3
"""yosugala official の公式ライブ映像から、曲単位のカタログ（catalog.json）を作る。

使い方（player フォルダで）:
    python3 tools/update_catalog.py
    python3 tools/update_catalog.py --cookies-from-browser chrome   # YouTube にボット確認で止められたとき
    python3 tools/update_catalog.py --offline   # YouTube に接続せず、video_cache.json だけで作り直す（補正ファイルを直したとき）

- 公式チャンネルの動画一覧から、ライブ映像（単独の Official Live Video とフルライブ）を拾う
- フルライブはチャプターで曲ごとに分ける（MC・SE などは除く）
- 動画ごとの情報は tools/video_cache.json に保存し、次回からは新しい動画だけを取得する
- 曲名の表記ゆれ・除外・終了時刻の調整などは tools/catalog_overrides.json で直す
- 最後に tools/make_song_pages.py で曲ごとの案内ページ（s/）も作り直す
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
CHANNEL_ID = 'UCP5_IRli-KbizrztKSmgh8Q'
CACHE = os.path.join(HERE, 'video_cache.json')
OVERRIDES = os.path.join(HERE, 'catalog_overrides.json')
OUT = os.path.join(ROOT, 'catalog.json')
SONG_IDS = os.path.join(HERE, 'song_ids.json')
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


def assign_ids(out):
    """曲ごとの ID（1 からの連番）を付ける。プレイリスト・共有リンク・曲の案内ページは、この ID で曲を指す。
    一度付けた ID は変えない・使い回さない（tools/song_ids.json に保存）。新しい曲には、古い動画（公開日）順・
    動画の中では開始の早い順に、続きの番号を付ける。前の曲との対応は「同じ動画の同じ曲名の何番目か」、
    なければ「同じ動画の同じ開始秒」で取るので、開始秒や曲名を直しても ID は変わらない（両方同時に変えると別の曲になる）。
    カタログからなくなった曲の ID は欠番として残す。"""
    recs = load(SONG_IDS, [])
    def occ_key(items):
        # 同じ動画・同じ曲名の何番目か（開始の早い順）
        seen, keys = {}, {}
        for x in sorted(items, key=lambda x: (x['vid'], x['start'])):
            k = (x['vid'], x['song']); seen[k] = seen.get(k, -1) + 1; keys[id(x)] = (x['vid'], x['song'], seen[k])
        return keys
    rk, ok = occ_key(recs), occ_key(out)
    by_occ = {rk[id(r)]: r for r in recs}
    by_start = {(r['vid'], r['start']): r for r in recs}
    used, new = set(), []
    for x in out:
        r = by_occ.get(ok[id(x)])
        if not r or r['id'] in used:
            r = by_start.get((x['vid'], x['start']))
        if r and r['id'] not in used:
            used.add(r['id']); x['id'] = r['id']; r.update(start=x['start'], song=x['song'])   # 今の開始秒・曲名を覚えておく
        else:
            new.append(x)
    nxt = max((r['id'] for r in recs), default=0) + 1
    for x in sorted(new, key=lambda x: (x['published'], x['vid'], x['start'])):
        x['id'] = nxt; recs.append({'id': nxt, 'vid': x['vid'], 'start': x['start'], 'song': x['song']}); nxt += 1
    recs.sort(key=lambda r: r['id'])
    with open(SONG_IDS, 'w', encoding='utf-8') as f:
        f.write('[\n' + ',\n'.join(json.dumps(r, ensure_ascii=False) for r in recs) + '\n]\n')
    if new:
        lo, hi = min(x['id'] for x in new), max(x['id'] for x in new)
        print(f'新しい曲に ID を付けました: {len(new)} 曲（{lo}' + (f'〜{hi}' if hi != lo else '') + '）')


def main():
    ov = load(OVERRIDES, {})
    aliases = ov.get('aliases', {})
    exclude_videos = set(ov.get('exclude_videos', []))
    exclude_entries = set(ov.get('exclude_entries', []))
    seg_fix = ov.get('segments', {})
    live_rules = [(re.compile(p, re.I), name) for p, name in ov.get('live_rules', [])]
    video_lives = ov.get('video_lives', {})
    # MC（メンバーが話している区間）: talks = [{ vid, start, end, title }]。フルライブ映像のチャプターと同じ形でカタログに入れ、
    # type = 'mc' を付ける（曲は type を付けない = 'song'）。kind は映像の種類（full）のまま
    talks = {}
    for t in ov.get('talks', []):
        talks.setdefault(t['vid'], []).append(t)
    cache = load(CACHE, {})

    entries = []
    if OFFLINE:
        print('--offline: video_cache.json の動画だけで作り直します')
        entries = [{'id': vid, 'title': info['title']} for vid, info in cache.items()]
    else:
        print('公式チャンネルの動画一覧を取得中…')
    for tab in ('videos', 'streams') if not OFFLINE else ():
        try:
            d = ytdlp_json(['--flat-playlist', f'{CHANNEL}/{tab}'])
            entries += [e for e in (d.get('entries') or []) if e]
        except RuntimeError as e:
            if tab == 'videos':
                sys.exit(f'動画一覧を取得できませんでした: {e}')
    # 「動画」と「ライブ」の両方の一覧に載っている動画は1本にまとめる（曲が二重に登録されないように）
    entries = list({e['id']: e for e in entries}.values())
    lives = [e for e in entries if LIVE_RE.search(e.get('title', '')) and e['id'] not in exclude_videos and not cache.get(e['id'], {}).get('mv')]
    print(f'ライブ映像: {len(lives)} 本（うち新しく情報を取得するもの: {sum(1 for e in lives if e["id"] not in cache)} 本）')
    # Official Music Video: 再生リスト「MusicVideo」の動画（video_cache.json では mv: true の印を付けて覚えておく）
    if OFFLINE:
        mvs = [{'id': vid, 'title': info['title']} for vid, info in cache.items() if info.get('mv')]
    else:
        try:
            mvs = [e for e in (ytdlp_json(['--flat-playlist', MV_PLAYLIST]).get('entries') or []) if e]
        except RuntimeError as e:
            print(f'Music Video の一覧を取得できませんでした（前回の分を使います）: {e}')
            mvs = [{'id': vid, 'title': info['title']} for vid, info in cache.items() if info.get('mv')]
        mvs += [e for e in entries if MV_TITLE_RE.match(e.get('title') or '')]
        mvs = list({e['id']: e for e in mvs}.values())
    mvs = [e for e in mvs if e['id'] not in exclude_videos]
    print(f'Music Video: {len(mvs)} 本（うち新しく情報を取得するもの: {sum(1 for e in mvs if e["id"] not in cache)} 本）')

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
    with open(CACHE, 'w', encoding='utf-8') as f:   # mv の印を付け足したときのため
        json.dump(cache, f, ensure_ascii=False, indent=1)

    songs = []
    for e in lives:
        vid = e['id']
        info = cache.get(vid)
        if not info:
            continue
        title, published = info['title'], iso(info.get('upload_date'))
        single = parse_single(title)
        if single and not (info['chapters'] and (info['duration'] or 0) > 1200):
            song, live = single
            songs.append({'song': song, 'vid': vid, 'start': 0, 'end': None, 'len': info['duration'],
                          'live': video_lives.get(vid) or live_by_rule(live_rules, title, live), 'tdate': title_date(title), 'published': published, 'kind': 'single'})
        elif info['chapters']:
            live = video_lives.get(vid) or live_by_rule(live_rules, title, parse_full_live(title))
            for c in info['chapters']:
                name = c['title'].strip()
                if SKIP_CHAPTER_RE.match(name):
                    continue
                start, end = int(c['start']), int(c['end'])
                songs.append({'song': name, 'vid': vid, 'start': start, 'end': end, 'len': end - start,
                              'live': live, 'tdate': title_date(title), 'published': published, 'kind': 'full'})
            for t in talks.get(vid, []):
                songs.append({'song': t['title'], 'vid': vid, 'start': t['start'], 'end': t['end'], 'len': t['end'] - t['start'],
                              'live': live, 'tdate': title_date(title), 'published': published, 'kind': 'full', 'type': 'mc'})
        else:
            print(f'  曲に分けられない動画をスキップ: {title[:60]}')
    # Official Music Video は1曲として（kind = 'mv'）。曲名はタイトルの「yosugala - 曲名」から
    for e in mvs:
        info = cache.get(e['id'])
        if not info:
            continue
        song = re.sub(r'^\s*yosugala\s*[-‐－–—]\s*', '', info['title'], flags=re.I)
        song = re.sub(r'\s*[\[［(（【][^\]］)）】]*(mv|music video)[^\]］)）】]*[\]］)）】]\s*$', '', song, flags=re.I).strip()
        songs.append({'song': song, 'vid': e['id'], 'start': 0, 'end': None, 'len': info['duration'],
                      'live': '', 'tdate': '', 'published': iso(info.get('upload_date')), 'kind': 'mv'})

    out = []
    for s in songs:
        key = f'{s["vid"]}@{s["start"]}'
        if key in exclude_entries:
            continue
        s['song'] = aliases.get(s['song'], s['song'])
        if key in seg_fix:
            # 開始・終了の補正（曲の前の SE や、曲のあとの MC・写真撮影を外す）。補正キーは元のチャプターの開始秒のまま
            fix = {k: v for k, v in seg_fix[key].items() if not k.startswith('_')}
            if 'start' in fix and fix['start'] != s['start']:
                s['chapter_start'] = s['start']   # 元の開始秒（ライブラリ編集ツール editor.html が補正キーを作るのに使う）
            if 'end' in fix and fix['end'] != s['end']:
                s['chapter_end'] = s['end']   # 元の終了秒（ライブラリ編集ツール editor.html に元のチャプターの位置として出す）
            if s.get('end') is None and 'start' in fix and s.get('len') is not None:
                s['len'] -= fix['start'] - s['start']   # 終わりが動画の最後の曲（単独映像）は、頭を削ったぶん短くなる
            s.update(fix)
            if s.get('end') is not None:
                s['len'] = s['end'] - s['start']
        out.append(s)
    # 同じ公演・同じ曲の単独映像があるフルライブのチャプターには、その単独映像の動画 ID を duplicate_of に書く
    # （どちらもプレイヤーに表示する。公演の中の曲順で、単独映像をチャプターの位置に入れるのに使う）
    singles = {(x['live'], x['song']): x['vid'] for x in out if x['kind'] == 'single' and x['live']}
    for x in out:
        key = (x['live'], x['song'])
        if x['kind'] == 'full' and key in singles:
            x['duplicate_of'] = singles[key]
    # 公演日: 補正ファイルの live_dates → タイトルの日付 の順で決める（分からなければ空）
    live_dates = ov.get('live_dates', {})
    for x in out:
        x['date'] = live_dates.get(x['live']) or x.pop('tdate', '') or ''
        x.pop('tdate', None)
    # 同じ公演でタイトルに日付がない映像は、ほかの映像の日付にそろえる（公演ごとのプレイリストから漏れないように）
    date_of = {}
    for x in out:
        if x['live'] and x['date']:
            date_of.setdefault(x['live'], x['date'])
    for x in out:
        if x['live'] and not x['date']:
            x['date'] = date_of.get(x['live'], '')
    # 会場名: 補正ファイルの live_venues（ライブ名 → 会場名）
    live_venues = ov.get('live_venues', {})
    for x in out:
        x['venue'] = live_venues.get(x['live'], '')
    # 公演の中の曲順 no（1 から）
    #   フルライブのチャプター → 開始時刻の順。単独映像 → 同じ曲のチャプターの位置（チャプターのすぐあと）
    #   フルライブ映像がない公演 → 補正ファイルの setlists（本編・アンコールの曲順）。どれでも分からなければ最後に公開日順
    setlists = ov.get('setlists', {})
    for live in {x['live'] for x in out if x['live']}:
        group = [x for x in out if x['live'] == live and x.get('type') != 'mc']   # MC には曲順を付けない
        chapter_at = {(x['duplicate_of'], x['song']): x['start'] for x in group if x.get('duplicate_of')}
        sl = setlists.get(live, {})
        setlist = sl.get('main', []) + sl.get('encore', [])
        encore_video = set(sl.get('encore_video', []))   # 本編とアンコールの両方で披露し、映像はアンコールのほうの曲

        def pos(x):
            if x['kind'] == 'full':
                return (0, x['start'], 0)
            if (x['vid'], x['song']) in chapter_at:
                return (0, chapter_at[(x['vid'], x['song'])], 1)
            if x['song'] in setlist:
                i = len(setlist) - 1 - setlist[::-1].index(x['song']) if x['song'] in encore_video else setlist.index(x['song'])
                return (1, i, 0)
            return (2, 0, x['published'])
        for i, x in enumerate(sorted(group, key=pos)):
            x['no'] = i + 1
    # 同じ曲の中は公演日の古い順（公演日が分からないものは公開日で比べる）
    out.sort(key=lambda s: (s['song'].casefold(), s['date'] or s['published']))

    # 公演ごとの情報（公演日・会場・セットリスト）。プレイヤーで公演ごとのプレイリストの説明に表示する
    lives = {}
    for x in out:
        if x['live'] and x['live'] not in lives:
            lives[x['live']] = {'date': x['date'], 'venue': x['venue'], **setlists.get(x['live'], {})}

    assign_ids(out)
    # タイトルの書き換え（曲 ID → タイトル。ライブラリ編集ツールで直したもの）。
    # 曲 ID は元のチャプター名で付けたあとなので、タイトルを変えても ID は変わらない
    titles = ov.get('titles', {})
    for x in out:
        t = titles.get(str(x['id']))
        if t:
            x['song'] = t
    if titles:
        out.sort(key=lambda s: (s['song'].casefold(), s['date'] or s['published']))

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'updated': datetime.date.today().isoformat(), 'count': len(out), 'lives': lives, 'songs': out},
                  f, ensure_ascii=False, indent=1)
    names = sorted({s['song'] for s in out if s.get('type') != 'mc'}, key=str.casefold)
    mc = [x for x in out if x.get('type') == 'mc']
    mv = [x for x in out if x['kind'] == 'mv']
    print(f'catalog.json を更新しました: 全 {len(out)} 件（{len(names)} 曲' + (f'・MC {len(mc)} 件' if mc else '') + (f'・Music Video {len(mv)} 本' if mv else '') + '）')
    print('曲名一覧: ' + ' / '.join(names))
    # 曲ごとの案内ページ（X で曲を共有したときのリンク先）もカタログに合わせて作り直す
    sys.path.insert(0, HERE); sys.dont_write_bytecode = True
    import make_song_pages
    make_song_pages.main(OFFLINE)


if __name__ == '__main__':
    main()
