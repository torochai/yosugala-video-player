#!/usr/bin/env python3
"""新しいライブ動画の「曲・MC の候補」を作る（ライブラリ編集ツール editor.html の「候補を読み込む」で読むファイル）。

使い方（player フォルダで。手元の PC で動かす前提）:
    python3 tools/find_candidates.py 動画ID … > candidates.json             # チャプター・概要欄だけ（音声は使わない）
    python3 tools/find_candidates.py --audio 動画ID … > candidates.json     # 音声も分析する（ダウンロード・文字起こし）
    python3 tools/find_candidates.py --audio --cookies-from-browser safari 動画ID …   # YouTube のボット確認で止められたとき

曲の候補（動画ごとに、上から順に使えるもの）:
  1. チャプター（MC・SE などのチャプターは除く。update_catalog.py と同じ）
  2. 概要欄のタイムスタンプ（「00:00 曲名」「1:02:03 曲名」の行）
  3. 音声の「音楽」の区間（名前は「（曲名なし）」）。--audio のときだけ
  --audio のときは、曲の頭の SE・終わりの歓声などを外した範囲を提案する（チャプターより短くするだけ。長くはしない）
MC の候補:
  曲と曲の間の 30 秒以上の空き（開演前・SE だけのチャプターの時間帯は除く）。名前は「MC①（次の曲のまえ）」
  --audio のときは、話し声が少ない空きは除き、文字起こし（text）を付ける。範囲は曲と曲の間のまま（カタログの MC も曲と曲の間すべて）
すでにカタログにある曲（同じ動画・同じ開始秒）・MC と重なる時間帯・talk_skips の時間帯は候補にしない。

ファイルの形: { "candidates": [ { id, kind, type, title, vid, start, end, date, live, venue, source, text? }, … ] }
  id・kind・type・title・vid・start・end は editor.html が必須にしている項目。source（chapter / description / audio）と
  text（MC の文字起こし）は確かめるための情報で、editor.html は読み飛ばす。

分析の結果（動画の情報・音声・特徴量・文字起こし）は --work のフォルダ（既定 ~/.cache/yosugala-candidates）に
動画ごとに残し、次からは使い回す（しきい値を変えて何度も試せるように）。リポジトリには入れない。
しきい値は --set 名前=値 で変えられる（名前は PARAMS）。正解との比べ方は tools/eval_candidates.py。

必要なもの: yt-dlp。--audio のときは numpy と faster-whisper（pip install numpy faster-whisper）。
"""
import argparse, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.dont_write_bytecode = True
import update_catalog as uc   # ライブ名・日付・チャプター名の判定を同じにする
uc.EXTRA = []   # update_catalog.py は起動時のオプションを yt-dlp に渡すので、こちらのオプションが混ざらないように空にする（必要なものは extra で渡す）

# しきい値（--set で変えられる。秒はすべて秒、音量は dB）
PARAMS = {
    'hop': 0.5,            # 特徴量の 1 コマの長さ（秒）
    'music_db': 15.0,      # 動画の中の大きい音（上位 10%）から何 dB 下までを「音楽の大きさ」とみなすか
    'music_flat': 0.35,    # スペクトルの平坦さがこれより小さい（音程がある）コマを音楽とみなす。歓声・拍手は平坦（大きい）
    'music_smooth': 4.0,   # 音楽の判定をならす幅（秒）
    'talk_smooth': 2.0,    # 話し声の判定をならす幅（秒）
    'vad_threshold': 0.5,  # 話し声の判定（Silero VAD）のしきい値
    'mc_min_gap': 30.0,    # 曲と曲の間がこれより短ければ MC の候補にしない
    'mc_talk_ratio': 0.2,  # 空きの中で話し声がこの割合より少なければ MC の候補にしない（--audio のとき）
    'trim_max': 900.0,     # 曲の範囲を縮める上限（前後それぞれ）。チャプターの終わりに 10 分を超える MC が入っていることもある
    'trim_keep': 60.0,     # 縮めたあとの曲がこれより短くなるなら縮めない（音楽の判定の失敗とみなす）
    'trim_pad': 1.0,       # 曲の範囲を音楽に縮めるときに前後に足す余白
    'trim_gap': 3.0,       # 曲の中のこれより短い「音楽でない」ところ（ブレイクなど）は曲の一部とみなす
    'trim_run': 10.0,      # 曲の範囲は、これより長く続く音楽の区間の最初から最後まで（曲の中の話し声の誤判定・短い切れ目で曲が割れても縮めすぎないように）
    'song_min': 90.0,      # 音声だけで曲を探すとき、これより短い音楽の区間は曲にしない
    'song_merge': 6.0,     # 音声だけで曲を探すとき、これより短い切れ目はつなげる
}
SE_RE = re.compile(r'^(se|opening|オープニング)$', re.I)
MC_RE = re.compile(r'^mc[①-⑳0-9]*$', re.I)
CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'
TS_RE = re.compile(r'^\s*[\[(（]?((?:\d{1,2}:)?\d{1,2}:\d{2})[\])）]?\s*[-－–—:：.・|｜]?\s*(.+?)\s*$')
NO_TITLE = '（曲名なし）'


def load(path, default):
    return uc.load(path, default)


def secs(ts):
    n = 0
    for p in ts.split(':'):
        n = n * 60 + int(p)
    return n


# ---- 動画の情報 ----------------------------------------------------------------

def video_info(vid, work, extra):
    """yt-dlp で動画の情報（タイトル・長さ・チャプター・概要欄・公開日）を取る。work/動画ID/info.json に残して使い回す"""
    path = os.path.join(work, vid, 'info.json')
    info = load(path, None)
    if info:
        return info
    d = uc.ytdlp_json([*extra, f'https://www.youtube.com/watch?v={vid}'])
    info = {'id': vid, 'title': d.get('title', ''), 'duration': d.get('duration'), 'upload_date': d.get('upload_date'),
            'description': d.get('description') or '',
            'chapters': [{'title': c['title'], 'start': c['start_time'], 'end': c['end_time']} for c in (d.get('chapters') or [])]}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    return info


def description_chapters(desc, duration):
    """概要欄の「00:00 曲名」の行をチャプターの形にする（2 行以上、時刻が増えていくものだけ）"""
    rows = []
    for line in (desc or '').splitlines():
        m = TS_RE.match(line)
        if m and m.group(2):
            rows.append((secs(m.group(1)), m.group(2)))
    rows = [r for i, r in enumerate(rows) if not i or r[0] > rows[i - 1][0]]
    if len(rows) < 2:
        return []
    ends = [r[0] for r in rows[1:]] + [duration or rows[-1][0]]
    return [{'title': t, 'start': s, 'end': e} for (s, t), e in zip(rows, ends) if e > s]


# ---- 音声の分析 ----------------------------------------------------------------

def audio_path(vid, work, extra, given=None):
    if given:
        return given
    d = os.path.join(work, vid)
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if f.startswith('audio.') and not f.endswith('.part'):
            return os.path.join(d, f)
    os.makedirs(d, exist_ok=True)
    print(f'  {vid}: 音声をダウンロード中…', file=sys.stderr)
    r = subprocess.run(['yt-dlp', '--no-warnings', '-q', *extra, '-f', 'bestaudio[ext=m4a]/bestaudio',
                        '-o', os.path.join(d, 'audio.%(ext)s'), f'https://www.youtube.com/watch?v={vid}'], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr.strip().splitlines() or ['unknown error'])[-1])
    return audio_path(vid, work, extra)


def features(samples, sr, hop):
    """コマ（hop 秒）ごとの音量（dB）とスペクトルの平坦さ（0〜1。雑音・歓声は 1 に近く、音程のある音は小さい）"""
    import numpy as np
    n = int(sr * hop)
    frames = len(samples) // n
    x = samples[:frames * n].reshape(frames, n).astype(np.float32)
    rms = np.sqrt(np.mean(x * x, axis=1) + 1e-12)
    rms_db = 20 * np.log10(rms + 1e-9)
    # 平坦さ: コマを 2048 サンプルずつに分けて平均したパワースペクトル（100〜8000 Hz）の 幾何平均 / 算術平均
    w = 2048
    k = max(1, n // w)
    sub = x[:, :k * w].reshape(frames, k, w) * np.hanning(w).astype(np.float32)
    p = np.mean(np.abs(np.fft.rfft(sub, axis=2)) ** 2, axis=1) + 1e-12
    f = np.fft.rfftfreq(w, 1 / sr)
    band = (f >= 100) & (f <= 8000)
    lp = np.log(p[:, band])
    flat = np.exp(lp.mean(axis=1)) / p[:, band].mean(axis=1)
    return [round(float(v), 1) for v in rms_db], [round(float(v), 3) for v in flat]


def speech_segments(samples, sr, threshold):
    from faster_whisper.vad import get_speech_timestamps, VadOptions
    ts = get_speech_timestamps(samples, VadOptions(threshold=threshold, min_silence_duration_ms=500, speech_pad_ms=200), sampling_rate=sr)
    return [[round(t['start'] / sr, 2), round(t['end'] / sr, 2)] for t in ts]


def decode(path, sr=16000):
    from faster_whisper.audio import decode_audio
    return decode_audio(path, sampling_rate=sr)


def analysis(vid, work, extra, params, given_audio=None):
    """work/動画ID/analysis.json（コマごとの音量・平坦さと、話し声の区間）。なければ音声から作る"""
    path = os.path.join(work, vid, 'analysis.json')
    key = {'hop': params['hop'], 'vad_threshold': params['vad_threshold']}
    a = load(path, None)
    if a and all(a.get(k) == v for k, v in key.items()):
        return a
    src = audio_path(vid, work, extra, given_audio)
    print(f'  {vid}: 音声を分析中…', file=sys.stderr)
    sr = 16000
    samples = decode(src, sr)
    rms_db, flat = features(samples, sr, params['hop'])
    a = {**key, 'rms_db': rms_db, 'flat': flat, 'speech': speech_segments(samples, sr, params['vad_threshold'])}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(a, f)
    return a


def smooth(flags, width):
    """真偽の並びを、前後 width コマの多数決でならす（短い途切れ・短いひげを消す）"""
    n, h = len(flags), max(0, int(width) // 2)
    if not h:
        return list(flags)
    acc = [0]
    for v in flags:
        acc.append(acc[-1] + (1 if v else 0))
    return [(acc[min(n, i + h + 1)] - acc[max(0, i - h)]) * 2 > min(n, i + h + 1) - max(0, i - h) for i in range(n)]


class Track:
    """分析の結果を、秒で問い合わせられるようにしたもの"""
    def __init__(self, a, params):
        self.hop = a['hop']
        db = sorted(a['rms_db'])
        ref = db[int(len(db) * 0.9)] if db else 0
        loud = [v >= ref - params['music_db'] for v in a['rms_db']]
        sp = [False] * len(a['rms_db'])
        for s, e in a['speech']:
            for i in range(int(s / self.hop), min(len(sp), int(e / self.hop) + 1)):
                sp[i] = True
        # 話し声は音程があり（平坦さが小さい）、音量も曲より少し小さいだけなので、音量・平坦さだけでは音楽と区別できない。
        # 話し声の判定（VAD）は歌声をほとんど拾わない（実測で曲の中の 1〜2%）ので、話し声のところは音楽から外す
        self.talk = smooth(sp, params['talk_smooth'] / self.hop)
        self.music = smooth([l and fl < params['music_flat'] and not t for l, fl, t in zip(loud, a['flat'], self.talk)], params['music_smooth'] / self.hop)

    def idx(self, t):
        return max(0, min(len(self.music), int(round(t / self.hop))))

    def runs(self, flags, start, end, merge=0.0):
        """[start, end) の中で flags が続く区間（秒）。merge 秒より短い切れ目はつなげる"""
        out, i0 = [], None
        a, b = self.idx(start), self.idx(end)
        for i in range(a, b + 1):
            on = i < b and flags[i]
            if on and i0 is None:
                i0 = i
            elif not on and i0 is not None:
                out.append([i0 * self.hop, i * self.hop]); i0 = None
        merged = []
        for r in out:
            if merged and r[0] - merged[-1][1] < merge:
                merged[-1][1] = r[1]
            else:
                merged.append(r)
        return merged

    def ratio(self, flags, start, end):
        a, b = self.idx(start), self.idx(end)
        return sum(1 for i in range(a, b) if flags[i]) / max(1, b - a)


def trim_song(track, start, end, params):
    """曲の範囲を「音楽が鳴っているところ」に縮める（頭の SE・終わりの歓声などを外す）。縮めすぎになるときは元のまま"""
    runs = track.runs(track.music, start, end, merge=params['trim_gap'])
    if not runs:
        return start, end
    long_runs = [r for r in runs if r[1] - r[0] >= params['trim_run']] or [max(runs, key=lambda r: r[1] - r[0])]
    best = [long_runs[0][0], long_runs[-1][1]]
    s = max(start, int(best[0] - params['trim_pad']))
    e = min(end, int(best[1] + params['trim_pad'] + 0.999))
    if s - start > params['trim_max']:
        s = start
    if end - e > params['trim_max']:
        e = end
    if e - s < params['trim_keep']:
        return start, end
    return s, e


def transcribe(vid, work, extra, spans, model_name, given_audio=None):
    """MC の範囲を文字起こしする（faster-whisper）。work/動画ID/text.json に範囲ごとに残す"""
    path = os.path.join(work, vid, 'text.json')
    done = load(path, {})
    todo = [(s, e) for s, e in spans if f'{model_name}:{s}-{e}' not in done]
    if todo:
        from faster_whisper import WhisperModel
        print(f'  {vid}: 文字起こし中（{len(todo)} か所、モデル {model_name}）…', file=sys.stderr)
        model = WhisperModel(model_name, device='auto', compute_type='int8')
        sr = 16000
        samples = decode(audio_path(vid, work, extra, given_audio), sr)
        for s, e in todo:
            segs, _ = model.transcribe(samples[int(s * sr):int(e * sr)], language='ja', vad_filter=True, condition_on_previous_text=False)
            done[f'{model_name}:{s}-{e}'] = ''.join(x.text.strip() for x in segs)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(done, f, ensure_ascii=False, indent=1)
    return {(s, e): done.get(f'{model_name}:{s}-{e}', '') for s, e in spans}


# ---- 候補を作る ------------------------------------------------------------------

def build(vid, opts, params=None, known=None):
    """1 本の動画の候補（曲・MC）を作る。known: すでにカタログにあるもの（skip_songs・mcs・talk_skips）。None なら何も除かない"""
    params = {**PARAMS, **(params or {})}
    ov = load(os.path.join(HERE, 'catalog_overrides.json'), {})
    info = video_info(vid, opts['work'], opts['extra']) if not opts.get('info') else opts['info']
    dur = info.get('duration') or 0
    title = info.get('title', '')
    track = Track(analysis(vid, opts['work'], opts['extra'], params, opts.get('audio_file')), params) if opts.get('audio') else None

    # 曲: チャプター → 概要欄のタイムスタンプ → 音声の音楽の区間
    source, chapters = None, []
    if not opts.get('no_chapters'):
        if info.get('chapters'):
            source, chapters = 'chapter', info['chapters']
        else:
            chapters = description_chapters(info.get('description'), dur)
            source = 'description' if chapters else None
    songs = []
    for c in chapters:
        name = c['title'].strip()
        if uc.SKIP_CHAPTER_RE.match(name):
            continue
        st, en = int(c['start']), int(c['end'])
        s, e = trim_song(track, st, en, params) if track else (st, en)
        songs.append({'title': name, 'start': s, 'end': e, 'chapter_start': st, 'chapter_end': en, 'source': source})
    if not chapters and track:
        source = 'audio'
        for s, e in track.runs(track.music, 0, dur, merge=params['song_merge']):
            if e - s >= params['song_min']:
                songs.append({'title': NO_TITLE, 'start': int(s), 'end': int(e + 0.999), 'chapter_start': int(s), 'chapter_end': int(e + 0.999), 'source': 'audio'})

    # MC: 曲と曲の間の空き（チャプター名が SE・opening だけの時間帯、開演前は除く）。
    # 空きは曲の範囲（--audio のときは縮めたあと）で測る。チャプターの終わりに MC が入っていることが多いため
    used = {s['chapter_start'] for s in songs}
    for i, s in enumerate(songs):
        s['ref'] = s['title'] if s['title'] != NO_TITLE else f'{i + 1}曲目'   # MC の名前で前後の曲を指すときの呼び方
    talks, t, prev = [], 0, None
    for s in songs + [None]:
        st = s['start'] if s else dur
        if prev and st - t >= params['mc_min_gap']:
            names = [c['title'].strip() for c in chapters if int(c['start']) < st and int(c['end']) > t and int(c['start']) not in used]
            rest = [n for n in names if not SE_RE.match(n)]
            if rest or not names:
                name = rest[0] if len(rest) == 1 and not MC_RE.match(rest[0]) else 'MC'
                talks.append({'name': name, 'after': prev['ref'], 'before': s['ref'] if s else None, 'start': int(t), 'end': int(st), 'source': source})
        if s:
            t, prev = max(t, s['end']), s
    if track:
        kept = []
        for x in talks:
            r = track.ratio(track.talk, x['start'], x['end'])
            if r < params['mc_talk_ratio'] or not r:
                print(f'  {vid}: {x["start"]}〜{x["end"]} 秒は話し声が少ない（{r:.0%}）ので MC の候補にしません', file=sys.stderr)
                continue
            x['talk_ratio'] = round(r, 2)
            kept.append(x)
        talks = kept
    n_mc = sum(1 for x in talks if x['name'] == 'MC')
    k = 0
    for x in talks:
        if x['name'] == 'MC' and n_mc > 1:
            x['name'] = 'MC' + CIRCLED[min(k, len(CIRCLED) - 1)]; k += 1
        x['title'] = f'{x["name"]}（{x["before"]}のまえ）' if x['before'] else f'{x["name"]}（{x["after"]}のあと）'
    if track and opts.get('transcribe') and talks:
        texts = transcribe(vid, opts['work'], opts['extra'], [(x['start'], x['end']) for x in talks], opts['model'], opts.get('audio_file'))
        for x in talks:
            x['text'] = texts[(x['start'], x['end'])]

    # すでにカタログにあるものは除く
    if known:
        songs = [s for s in songs if (vid, s['chapter_start']) not in known['songs']]
        talks = [x for x in talks if f'{vid}@{x["start"]}' not in known['skips']
                 and not any(v == vid and a < x['end'] and x['start'] < b for v, a, b in known['mcs'])]

    single = uc.parse_single(title)
    kind = 'single' if single and not chapters else 'full'
    live = ov.get('video_lives', {}).get(vid) or uc.live_by_rule([(re.compile(p, re.I), n) for p, n in ov.get('live_rules', [])], title,
                                                                 single[1] if single else uc.parse_full_live(title))
    date = ov.get('live_dates', {}).get(live) or uc.title_date(title)
    venue = ov.get('live_venues', {}).get(live, '')
    out = []
    for x in songs:
        out.append({'kind': kind, 'type': 'song', 'title': x['title'], 'vid': vid, 'start': x['start'], 'end': x['end'],
                    'date': date, 'live': live, 'venue': venue, 'source': x['source'],
                    **({'chapter_start': x['chapter_start'], 'chapter_end': x['chapter_end']}
                       if (x['start'], x['end']) != (x['chapter_start'], x['chapter_end']) else {})})
    for x in talks:
        out.append({'kind': kind, 'type': 'mc', 'title': x['title'], 'vid': vid, 'start': x['start'], 'end': x['end'],
                    'date': date, 'live': live, 'venue': venue, 'source': x['source'] or 'audio',
                    **({'talk_ratio': x['talk_ratio']} if 'talk_ratio' in x else {}), **({'text': x['text']} if 'text' in x else {})})
    return sorted(out, key=lambda c: c['start'])


def known_from_catalog():
    """カタログにすでにある曲（動画ID と元の開始秒）・MC と、talk_skips"""
    songs = load(os.path.join(ROOT, 'catalog.json'), {}).get('songs', [])
    ov = load(os.path.join(HERE, 'catalog_overrides.json'), {})
    return {'songs': {(s['vid'], s.get('chapter_start', s['start'])) for s in songs if s.get('type') != 'mc'},
            'mcs': [(s['vid'], s['start'], s['end']) for s in songs if s.get('type') == 'mc'],
            'skips': set(ov.get('talk_skips', []))}


def parse_set(items):
    params = {}
    for it in items or []:
        k, _, v = it.partition('=')
        if k not in PARAMS:
            sys.exit(f'--set の名前が違います: {k}（使える名前: {", ".join(PARAMS)}）')
        params[k] = float(v)
    return params


def common_args(p):
    p.add_argument('--audio', action='store_true', help='音声も分析する（ダウンロード・特徴量・話し声の区間）')
    p.add_argument('--no-text', action='store_true', help='--audio のとき、MC の文字起こしをしない')
    p.add_argument('--model', default='small', help='文字起こしのモデル（faster-whisper。tiny / base / small / medium / large-v3）')
    p.add_argument('--work', default=os.path.expanduser('~/.cache/yosugala-candidates'), help='分析の結果を残すフォルダ（リポジトリの外）')
    p.add_argument('--set', action='append', metavar='名前=値', help='しきい値を変える（例: --set mc_talk_ratio=0.3）')
    p.add_argument('--cookies-from-browser', metavar='ブラウザ', help='yt-dlp に渡す（safari / chrome など）')


def opts_from(a):
    return {'audio': a.audio, 'transcribe': a.audio and not a.no_text, 'model': a.model, 'work': os.path.abspath(a.work),
            'extra': ['--cookies-from-browser', a.cookies_from_browser] if a.cookies_from_browser else []}


def main():
    p = argparse.ArgumentParser(description='新しいライブ動画の曲・MC の候補を作る（editor.html の「候補を読み込む」用）')
    p.add_argument('vids', nargs='+', metavar='動画ID')
    p.add_argument('--audio-file', help='ダウンロードの代わりに使う音声ファイル（動画 1 本のとき）')
    p.add_argument('--all', action='store_true', help='すでにカタログにある曲・MC も候補に入れる')
    common_args(p)
    a = p.parse_args()
    opts, params = opts_from(a), parse_set(a.set)
    if a.audio_file:
        if len(a.vids) != 1:
            sys.exit('--audio-file は動画 1 本のときだけ使えます')
        opts['audio_file'] = os.path.abspath(a.audio_file)
    known = None if a.all else known_from_catalog()
    out = []
    for vid in a.vids:
        try:
            out += build(vid, opts, params, known)
        except RuntimeError as e:
            print(f'{vid} の情報を取得できませんでした: {e}', file=sys.stderr)
            print('YouTube のボット確認で止められた場合は --cookies-from-browser safari（または chrome）を付けて実行してください。', file=sys.stderr)
            sys.exit(1)
    for i, c in enumerate(out):
        c['id'] = i + 1
    out = [{'id': c.pop('id'), **c} for c in out]
    json.dump({'candidates': out}, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write('\n')
    n_song = sum(1 for c in out if c['type'] == 'song')
    print(f'候補: {len(out)} 件（曲 {n_song} 件・MC {len(out) - n_song} 件）', file=sys.stderr)
    for c in out:
        if c.get('text'):
            print(f'  {c["title"]} {c["start"]}〜{c["end"]}: {c["text"][:60]}', file=sys.stderr)


if __name__ == '__main__':
    main()
