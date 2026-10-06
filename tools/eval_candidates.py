#!/usr/bin/env python3
"""find_candidates.py の候補を、今のカタログ（catalog.json）を正解として比べる。しきい値を決めるのに使う。

使い方（player フォルダで。--audio は手元の PC で）:
    python3 tools/eval_candidates.py                         # カタログのフルライブ映像すべて。チャプターだけ（音声なし）
    python3 tools/eval_candidates.py --audio                 # 音声も使う（初回はダウンロード・分析に時間がかかる）
    python3 tools/eval_candidates.py --audio --no-chapters   # チャプターを使わず、音声だけで曲を探したときの出来
    python3 tools/eval_candidates.py --audio --set mc_talk_ratio=0.3 -v   # しきい値を変える・外れたものを一つずつ出す
    python3 tools/eval_candidates.py 動画ID …                # 動画を指定する

正解: カタログの曲（kind = full。範囲は segments の補正後）と MC（type = mc）。talk_skips は「MC ではない」正解として数える。
対応づけ: 候補と正解が、短いほうの長さの半分以上重なっていれば同じものとみなす（重なりの大きい順に 1 対 1）。
出すもの: 見つけ漏れ（正解にあって候補にない）・余計な候補（候補にあって正解にない）の数と、開始・終了のずれ（秒）。
動画の情報は data/youtube.json を使う（概要欄は入っていないので、--no-chapters のときは音声だけで曲を探す）。
"""
import argparse, os, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.dont_write_bytecode = True
import find_candidates as fc


def overlap(a, b):
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def match(cands, truth):
    """短いほうの半分以上重なる組を、重なりの大きい順に 1 対 1 で対応づける"""
    pairs = sorted(((overlap(c, t), i, j) for i, c in enumerate(cands) for j, t in enumerate(truth)
                    if overlap(c, t) * 2 >= min(c[1] - c[0], t[1] - t[0])), reverse=True)
    ci, ti, out = set(), set(), []
    for _, i, j in pairs:
        if i not in ci and j not in ti:
            ci.add(i); ti.add(j); out.append((i, j))
    return out


def score(cands, truth):
    m = match(cands, truth)
    ds = [abs(cands[i][0] - truth[j][0]) for i, j in m]
    de = [abs(cands[i][1] - truth[j][1]) for i, j in m]
    return {'truth': len(truth), 'cand': len(cands), 'hit': len(m), 'miss': len(truth) - len(m), 'extra': len(cands) - len(m),
            'ds': ds, 'de': de, 'pairs': m}


def fmt_d(xs):
    if not xs:
        return '      -'
    return f'{statistics.mean(xs):5.1f}/{max(xs):3.0f}'


def t(s):
    s = int(s)
    return f'{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}' if s >= 3600 else f'{s // 60}:{s % 60:02d}'


def main():
    p = argparse.ArgumentParser(description='候補をカタログ（正解）と比べる')
    p.add_argument('vids', nargs='*', metavar='動画ID')
    p.add_argument('--no-chapters', action='store_true', help='チャプターを使わない（音声だけで曲を探す出来を見る）')
    p.add_argument('-v', '--verbose', action='store_true', help='見つけ漏れ・余計な候補・大きくずれたものを一つずつ出す')
    fc.common_args(p)
    a = p.parse_args()
    opts, params = fc.opts_from(a), fc.parse_set(a.set)
    opts['no_chapters'] = a.no_chapters
    opts['transcribe'] = False   # 比べるのに文字起こしはいらない
    songs = fc.load(os.path.join(ROOT, 'data', 'catalog.json'), {}).get('songs', [])
    cache = fc.load(os.path.join(ROOT, 'data', 'youtube.json'), {})
    skips = set(fc.load(os.path.join(HERE, 'catalog_overrides.json'), {}).get('talk_skips', []))
    vids = a.vids or sorted({s['vid'] for s in songs if s['kind'] == 'full'}, key=lambda v: cache.get(v, {}).get('upload_date') or '')
    print(f'条件: {"音声あり" if a.audio else "音声なし"}・{"チャプターなし" if a.no_chapters else "チャプターあり"}'
          + (f'・{", ".join(f"{k}={v:g}" for k, v in params.items())}' if params else ''))
    print('曲・MC ごとに「正解 / 候補 / 見つけ漏れ / 余計」と、開始・終了のずれ（秒。平均/最大）')
    print(f'{"動画":<12} | {"曲":^15} {"開始":^9} {"終了":^9} | {"MC":^15} {"開始":^9} {"終了":^9} | 余計な MC のうち talk_skips')
    tot = {'song': [], 'mc': []}
    for vid in vids:
        if vid not in cache:
            print(f'{vid}: youtube.json にないので飛ばします'); continue
        got = fc.build(vid, {**opts, 'info': {**cache[vid], 'id': vid}}, params)
        rows = {}
        for kind in ('song', 'mc'):
            truth = sorted([(s['start'], s['end'], s['song']) for s in songs if s['vid'] == vid and s['kind'] == 'full'
                            and (s.get('type') == 'mc') == (kind == 'mc')])
            cand = [(c['start'], c['end'], c['title']) for c in got if c['type'] == kind]
            r = score(cand, truth); r['vid'] = vid; r['c'] = cand; r['t'] = truth
            tot[kind].append(r); rows[kind] = r
        s, m = rows['song'], rows['mc']
        hit = {i for i, _ in m['pairs']}
        ex_skip = sum(1 for i, c in enumerate(m['c']) if i not in hit and any(
            k.startswith(vid + '@') and abs(int(k.split('@')[1]) - c[0]) < 60 for k in skips))
        print(f'{vid:<12} | {s["truth"]:3}/{s["cand"]:3}/{s["miss"]:3}/{s["extra"]:3} {fmt_d(s["ds"])} {fmt_d(s["de"])} | '
              f'{m["truth"]:3}/{m["cand"]:3}/{m["miss"]:3}/{m["extra"]:3} {fmt_d(m["ds"])} {fmt_d(m["de"])} | {ex_skip}')
        if a.verbose:
            for kind, r in (('曲', s), ('MC', m)):
                ci = {i for i, _ in r['pairs']}; ti = {j for _, j in r['pairs']}
                for j, x in enumerate(r['t']):
                    if j not in ti:
                        print(f'    {kind}の見つけ漏れ: {t(x[0])}〜{t(x[1])} {x[2]}')
                for i, x in enumerate(r['c']):
                    if i not in ci:
                        print(f'    余計な{kind}の候補: {t(x[0])}〜{t(x[1])} {x[2]}')
                for i, j in r['pairs']:
                    c, x = r['c'][i], r['t'][j]
                    if abs(c[0] - x[0]) > 5 or abs(c[1] - x[1]) > 5:
                        print(f'    {kind}のずれ: {x[2]} 正解 {t(x[0])}〜{t(x[1])} / 候補 {t(c[0])}〜{t(c[1])}（{c[0] - x[0]:+d}・{c[1] - x[1]:+d} 秒）')
    print('-' * 100)
    for kind, label in (('song', '曲'), ('mc', 'MC')):
        rs = tot[kind]
        ds = [d for r in rs for d in r['ds']]; de = [d for r in rs for d in r['de']]
        n = lambda k: sum(r[k] for r in rs)
        within = sum(1 for x, y in zip(ds, de) if x <= 5 and y <= 5)
        print(f'{label}: 正解 {n("truth")}・候補 {n("cand")}・見つけた {n("hit")}・見つけ漏れ {n("miss")}・余計 {n("extra")}'
              f'／開始のずれ 平均 {statistics.mean(ds) if ds else 0:.1f} 秒・終了のずれ 平均 {statistics.mean(de) if de else 0:.1f} 秒'
              f'／前後とも 5 秒以内 {within}/{len(ds)}')


if __name__ == '__main__':
    main()
