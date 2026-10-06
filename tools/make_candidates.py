#!/usr/bin/env python3
"""ライブラリ編集ツール（editor.html）で読み込む「候補」のファイルを作る。

いまは MC の候補だけを作る（曲はフルライブ映像のチャプターからカタログに入っている）:
  フルライブ映像の中で、どの曲にも使われていない 30 秒以上の時間帯を MC の候補にする。
  - 開演前（1曲目より前）と、チャプター名が SE・opening だけの時間帯は入れない（曲が流れるだけのため）
  - 名前は「MC①（次の曲のまえ）」（MC の中で次の曲を振ることが多いため）。次の曲がない（終演後）ときは「（前の曲のあと）」。
    同じ公演の MC には、公演の中の順に ①②③… を付ける
    チャプター名が「バンド紹介」「ending MC」など MC 以外の名前ならその名前を使う
  - すでにカタログに入っている MC（type = "mc"）と重なる時間帯は入れない
  - 確かめて要らなかった時間帯（catalog_overrides.json の talk_skips に「動画ID@開始秒」）は入れない
話しているかどうかは分からないので、調整ツールで聞いて、要らないものに「不要」の印を付ける。

ファイルの形: { "candidates": [ { id: 仮 ID（1 からの数字）, kind: "full" | "single", type: "song" | "mc", title, vid, start, end, date, live, venue }, … ] }
  kind は映像の種類（フルライブ映像・単独映像。catalog.json と同じ）、type は中身の種類（曲・MC。あとでイントロなどを足すときは種類を増やす）

使い方（player フォルダで）:
    python3 tools/make_candidates.py > candidates.json            # すべてのフルライブ映像
    python3 tools/make_candidates.py 動画ID … > candidates.json   # 指定した動画だけ
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MIN_GAP = 30   # 秒。これより短い空きは曲間のつなぎとみなして入れない
SE_RE = re.compile(r'^(se|opening|オープニング)$', re.I)
MC_RE = re.compile(r'^mc[①-⑳0-9]*$', re.I)   # 「MC」「MC①」など（番号を付け直す）
CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'


def main(vids):
    with open(os.path.join(ROOT, 'catalog.json'), encoding='utf-8') as f:
        songs = json.load(f)['songs']
    with open(os.path.join(HERE, 'video_cache.json'), encoding='utf-8') as f:
        cache = json.load(f)
    with open(os.path.join(HERE, 'catalog_overrides.json'), encoding='utf-8') as f:
        skips = set(json.load(f).get('talk_skips', []))
    full, have = {}, []
    for s in songs:
        if s['kind'] == 'full' and s.get('type', 'song') == 'song':
            full.setdefault(s['vid'], []).append(s)
        if s.get('type') == 'mc':
            have.append((s['vid'], s['start'], s['end']))
    out = []
    for vid, group in sorted(full.items(), key=lambda kv: (kv[1][0]['date'], kv[0])):
        if vids and vid not in vids:
            continue
        info, group = cache[vid], sorted(group, key=lambda s: s['start'])
        dur, used = info['duration'], {s.get('chapter_start', s['start']) for s in group}
        talks, t, prev = [], 0, None
        for s in group + [None]:
            st = s['start'] if s else dur
            if prev and st - t >= MIN_GAP:
                names = [c['title'].strip() for c in info['chapters']
                         if int(c['start']) < st and int(c['end']) > t and int(c['start']) not in used]
                rest = [n for n in names if not SE_RE.match(n)]
                if rest or not names:   # チャプター名が SE・opening だけの時間帯は入れない
                    name = rest[0] if len(rest) == 1 and not MC_RE.match(rest[0]) else 'MC'
                    talks.append({'name': name, 'after': prev['song'], 'before': s['song'] if s else None, 'start': t, 'end': st})
            if s:
                t, prev = max(t, s['end'] if s['end'] is not None else dur), s
        n_mc = sum(1 for x in talks if x['name'] == 'MC')
        k = 0
        for x in talks:
            if x['name'] == 'MC' and n_mc > 1:
                x['name'] = 'MC' + CIRCLED[k]; k += 1
            if f'{vid}@{x["start"]}' in skips or any(v == vid and a < x['end'] and x['start'] < b for v, a, b in have):
                continue
            g = group[0]
            out.append({'id': len(out) + 1, 'kind': 'full', 'type': 'mc', 'title': f'{x["name"]}（{x["before"]}のまえ）' if x['before'] else f'{x["name"]}（{x["after"]}のあと）', 'vid': vid,
                        'start': x['start'], 'end': x['end'], 'date': g['date'], 'live': g['live'], 'venue': g['venue']})
    json.dump({'candidates': out}, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write('\n')
    print(f'候補: {len(out)} 件', file=sys.stderr)


if __name__ == '__main__':
    main(set(sys.argv[1:]))
