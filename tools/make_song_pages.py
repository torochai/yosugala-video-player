#!/usr/bin/env python3
"""曲ごとの案内ページ（s/曲ID.html）を catalog.json から作る。曲 ID は tools/song_ids.json の連番。

プレーヤーの「この曲を共有」で X に貼るリンク用。X のカードにその曲の YouTube のサムネ・曲名・公演が出て、
開くとすぐプレーヤーのその曲（../?song=曲ID）に移る。?lib=… が付いていれば、そのプレイリストで開く。
「再生位置」の共有では ?t=動画の秒 が付き、プレーヤーはその位置から再生する。

使い方（player フォルダで）:
    python3 tools/make_song_pages.py             # サムネの大きい画像があるかを YouTube に確かめる（結果は tools/thumb_cache.json に保存）
    python3 tools/make_song_pages.py --offline   # 確かめずに thumb_cache.json だけで作る（未確認の動画は中くらいの画像）
tools/update_catalog.py を実行すると、最後にこれも実行される。
"""
import html, json, os, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CATALOG = os.path.join(ROOT, 'data', 'catalog.json')
OUT_DIR = os.path.join(ROOT, 's')
THUMB_CACHE = os.path.join(HERE, 'thumb_cache.json')
SITE = 'https://torochai.github.io/yosugala-video-player/'


def thumb_name(vid, cache, offline):
    """大きいサムネ（maxresdefault 1280x720）があればそれ、なければ hqdefault（480x360、どの動画にもある）"""
    if vid in cache:
        return cache[vid]
    if offline:
        return 'hqdefault'
    name = 'hqdefault'
    try:
        req = urllib.request.Request(f'https://i.ytimg.com/vi/{vid}/maxresdefault.jpg', method='HEAD')
        with urllib.request.urlopen(req, timeout=15) as r:
            if r.status == 200:
                name = 'maxresdefault'
    except Exception:
        pass
    cache[vid] = name
    return name


def dot(d):
    return d.replace('-', '.') if d else ''


def quote_live(live):
    return f'「{live.replace("「", "『").replace("」", "』")}」' if live else ''


def page(s, thumb):
    vid, sid, song = s['vid'], s['id'], s['song']
    where = dot(s.get('date')) + quote_live(s.get('live'))
    if s.get('venue'):
        where += f'@ {s["venue"]}'
    if s.get('kind') == 'mv':
        where = 'Official Music Video'
    title = f'♫ {song} ／ yosugala'
    desc = f'{where} ｜ yosugala Live Video Player' if where else 'yosugala Live Video Player'
    url = f'{SITE}s/{sid}.html'
    img = f'https://i.ytimg.com/vi/{vid}/{thumb}.jpg'
    song_key = str(sid)
    e = lambda x: html.escape(x, quote=True)
    return f'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="yosugala Live Video Player">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(url)}">
<meta property="og:image" content="{e(img)}">
<meta property="og:locale" content="ja_JP">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(title)}">
<meta name="twitter:description" content="{e(desc)}">
<meta name="twitter:image" content="{e(img)}">
<meta name="robots" content="noindex">
<noscript><meta http-equiv="refresh" content="0; url=../?song={song_key}"></noscript>
<script>
  // ?lib=… が付いていればそのプレイリストで、なければ公演のプレイリストでこの曲を開く。?t=秒 は再生位置の共有（その位置から再生）。
  // # ではなく ? で渡す（X アプリの中のブラウザは、移るときに # 以降を落とすことがあるため）
  var q = new URLSearchParams(location.search), lib = q.get('lib'), t = q.get('t');
  location.replace('../?' + (lib ? 'lib=' + encodeURIComponent(lib) + '&' : '') + 'song={song_key}' + (/^\\d+$/.test(t || '') ? '&t=' + t : ''));
</script>
<style>body {{ margin: 0; background: #05060f; color: #e9ecf8; font-family: sans-serif; display: grid; place-items: center; min-height: 100vh; }} a {{ color: #b9cbff; }}</style>
</head>
<body>
<p><a href="../?song={song_key}">{e(song)} をプレーヤーで開く</a></p>
</body>
</html>
'''


def main(offline=False):
    with open(CATALOG, encoding='utf-8') as f:
        songs = json.load(f)['songs']
    try:
        with open(THUMB_CACHE, encoding='utf-8') as f:
            cache = json.load(f)
    except FileNotFoundError:
        cache = {}
    os.makedirs(OUT_DIR, exist_ok=True)
    want = set()
    for s in songs:
        name = f'{s["id"]}.html'
        want.add(name)
        with open(os.path.join(OUT_DIR, name), 'w', encoding='utf-8') as f:
            f.write(page(s, thumb_name(s['vid'], cache, offline)))
    # カタログからなくなった曲のページは消す（ほかのファイルは触らない）
    for name in os.listdir(OUT_DIR):
        if name.endswith('.html') and name not in want:
            os.remove(os.path.join(OUT_DIR, name))
    with open(THUMB_CACHE, 'w', encoding='utf-8') as f:
        json.dump(dict(sorted(cache.items())), f, ensure_ascii=False, indent=1)
    big = sum(1 for v in {s['vid'] for s in songs} if cache.get(v) == 'maxresdefault')
    print(f'曲ごとの案内ページを作りました: {len(want)} ページ（s/）／大きいサムネのある動画 {big} 本')


if __name__ == '__main__':
    main('--offline' in sys.argv[1:])
