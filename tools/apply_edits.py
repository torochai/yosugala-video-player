#!/usr/bin/env python3
"""ライブラリ編集ツール（editor.html）で「書き出す」したファイルを、data/catalog.json に書き込む。

使い方（player フォルダで）:
    python3 tools/apply_edits.py yosugala-segments-20261007-1200.json

書き出したファイルの形（editor.html の renderOut）:
  segments: { "動画ID@元のチャプターの開始秒": { start, end, _memo }, … }   曲・MC の範囲を直したもの
  titles:   { "曲 ID": "新しいタイトル", … }                                 タイトルを直したもの
  add:      [ { kind, type, title, vid, start, end, live, … }, … ]           候補から足すもの（新しい曲 ID を付ける）
書き込んだあと、update_catalog.py の finish() で計算で出す値と案内ページ（s/）を作り直す（YouTube には接続しない）。
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.dont_write_bytecode = True
import update_catalog as uc


def apply(cat, edits):
    """edits を cat に書き込む。直した件数を返す。見つからない曲があれば ValueError"""
    items = cat['items']
    by_id = {x['id']: x for x in items}
    by_key = {f'{x["vid"]}@{x.get("chapter_start", x["start"])}': x for x in items}
    n = 0
    for key, v in (edits.get('segments') or {}).items():
        x = by_key.get(key)
        if not x:
            raise ValueError(f'範囲を直す曲が見つかりません: {key}')
        # chapter_start・chapter_end は元のチャプターの位置。元と違う範囲になったときだけ書く（editor.html が補正キーと元の位置に使う）
        orig = {'start': x.get('chapter_start', x['start']), 'end': x.get('chapter_end', x.get('end'))}
        for k in ('start', 'end'):
            if k in v:
                x[k] = v[k]
            if x.get(k) != orig[k]:
                x['chapter_' + k] = orig[k]
            else:
                x.pop('chapter_' + k, None)
        n += 1
    for sid, title in (edits.get('titles') or {}).items():
        x = by_id.get(int(sid))
        if not x:
            raise ValueError(f'タイトルを直す曲が見つかりません: ID {sid}')
        x['title'] = title
        n += 1
    new = []
    for c in edits.get('add') or []:
        # date は公演が lives にまだないときに、その公演日として使う（項目の date は finish() が lives から付け直す）
        x = {'title': c['title'], 'vid': c['vid'], 'start': c['start'], 'end': c.get('end'), 'kind': c.get('kind', 'full'), 'live': c.get('live', ''), 'date': c.get('date', '')}
        if c.get('type') == 'mc':
            x['type'] = 'mc'
        new.append(x)
    uc.add_items(cat, new)
    return n + len(new)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    with open(sys.argv[1], encoding='utf-8') as f:
        edits = json.load(f)
    cat = uc.load_catalog()
    try:
        n = apply(cat, edits)
    except ValueError as e:
        sys.exit(f'書き込めませんでした（catalog.json は変えていません）: {e}')
    print(f'書き込みました: {n} 件')
    uc.finish(cat, uc.load(uc.CACHE, {}), offline=True)


if __name__ == '__main__':
    main()
