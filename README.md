# yosugala video player

yosugala official の公式ライブ映像（YouTube）から好きな曲だけを集めて、自分だけのセットリストで続けて再生できる非公式のファンメイドプレイヤーです。フルライブ映像の中の1曲だけを切り出して再生することもできます。

https://torochai.github.io/yosugala-video-player/

- フルライブ映像の中の曲は、その曲の部分だけを再生します
- プレイリストの作成・編集（ライブ映像の一覧から追加・並べ替え・削除）、複数プレイリスト
- 共有リンク、書き出し / 読み込み
- リピート（全曲 / 1曲）、全画面再生
- Official Music Video（公開日順）
- ライブMC集（フルライブ映像の中で、メンバーが話している区間を公演日順に）
- 再生中の曲から「この公演の続き」「別公演の同じ曲」へ移る（止めずに続けて再生。「戻る」で元のプレイリストへ）
- ライブラリ編集ツール（タイトル行の右端のギア）: 曲・MC の開始・終了とタイトルを直して、このブラウザのプレーヤーにすぐ反映・書き出し。新しい曲・MC の候補ファイルを読み込んで足すこともできる

映像はすべて YouTube の埋め込みで公式動画を再生しています。映像・楽曲の権利は yosugala および各権利者に帰属します。
このページは yosugala 公式とは関係ありません。

## ライブ映像の一覧（data/catalog.json）

プレイヤーのライブラリにある次のプレイリストは `data/catalog.json` から作られます。

- すべてのライブ映像 - 曲名順（同じ曲の中は公演日の古い順）
- すべてのライブ映像 - 公演日順（公演日の古い順。同じ公演の中はセットリスト順）
- Official Live Video - 公開日順（1曲ずつ公開された映像だけ。公開日の古い順）
- 公演ごとのプレイリスト「YYYY.MM.DD「公演名」」（新しい公演が上。曲はセットリスト順）
  - フルライブ映像がある公演は、フルライブ映像のチャプターだけで作ります（単独映像もある曲も、チャプターのほうを使います）。フルライブ映像がない公演は単独映像で作ります

曲の行には「YYYY.MM.DD「公演名」 @ 会場名」と表示します。

### データ

- `data/catalog.json`：元データ。**手で直すのはここだけ**です
  - `items`：曲・MC・Music Video の一覧。1 件ずつ `id`（曲 ID）・`title`・`vid`・`start`・`end`・`kind`（`full` フルライブ映像のチャプター / `single` 単独映像 / `mv` Music Video）・`type`（MC は `"mc"`）・`live`（公演名）を持ちます。`chapter_start`・`chapter_end` は範囲を直す前の元のチャプターの位置です
  - `len`・`published`・`date`・`venue`・`no`（公演の中の曲順）・`duplicate_of` は計算で出す値です。手で直さず、`update_catalog.py` に付け直させます
  - `lives`：公演ごとの `date`（公演日）・`venue`（会場名）とセットリスト（`main` 本編・`encore` アンコール・`medley` メドレーの曲・`source` 出典（複数なら配列）・`note` 補足・`encore_video` 本編とアンコールの両方で披露した曲のうち映像がアンコールのほうの曲）。セットリストは公演ごとのプレイリストの「このプレイリストについて」に表示します
  - `import`：新しい動画を取り込むときの決まり（`aliases` 曲名の表記ゆれ・`live_rules` 動画タイトル（正規表現）→ 公演名・`video_lives` 動画 ID → 公演名・`exclude_videos` / `exclude_entries` 取り込まない動画・チャプター（`動画ID@開始秒`）・`talk_skips` MC の候補として確かめて要らなかった時間帯）
  - `next_id`：次に付ける曲 ID
- `data/youtube.json`：YouTube から取った動画の情報（タイトル・長さ・公開日・チャプター・MV かどうか・サムネの大きさ）。ツールだけが書きます
- `data/playlists.json`：プレイリストの定義。`builtin` はトロ's セレクション（名前・作成者・説明と、曲 ID の並び `items`）。`library` はライブラリのプレイリストを表示する順に並べたもので、`key`（共有リンクの呼び名）・`name`・`desc` を持ちます。どの曲を選んでどう並べるかは `index.html` が `key` ごとに決めます（`key` が `lives` のところに公演ごとのプレイリストが入ります）。`desc` の `{count}`・`{updated}`・`{about}`・`{help}` はプレーヤーが置き換えます。手で直したら、そのまま push すれば反映されます

### 新しい動画を足す

公式チャンネルに新しいライブ映像・Music Video が出たら、次のコマンドで足して push してください（yt-dlp が必要です）。

```bash
python3 tools/update_catalog.py
git add data/ s/ && git commit -m "Update catalog" && git push
```

- `data/catalog.json` にまだ 1 曲も入っていない動画だけを足します。すでにある曲・MC には触らないので、手で直した内容は消えません
  - ある動画の曲を `items` から全部消すと、次に実行したときにその動画が足し直されます。取り込みたくない動画は `import.exclude_videos`、取り込みたくないチャプターは `import.exclude_entries` に書いてください
- 単独の「Official Live Video」は1曲として、フルライブ映像はチャプターで曲ごとに分けて足します（MC・SE などは除外）。曲名は `import.aliases` でそろえ、公演名は `import.video_lives` → `import.live_rules` → 動画タイトル の順で決めます。新しい公演は `lives` に足します（公演日はタイトルの日付から。会場名は手で書きます）
- 曲 ID は `next_id` から順に付けます。プレイリスト・共有リンク・書き出しの JSON・曲の案内ページ（`s/曲ID.html`）は、この ID で曲を指します。一度付けた ID は変えず、使い回しません
- 一度取得した動画の情報は `data/youtube.json` に保存され、次回からは新しい動画だけを取得します
- YouTube のボット確認で止められたときは `python3 tools/update_catalog.py --cookies-from-browser chrome` で実行してください
- Official Music Video は、公式チャンネルの再生リスト「MusicVideo」の動画と、タイトルがちょうど「yosugala - 曲名」の動画（再生リストに入っていない新しい MV のため）を `kind: "mv"` で入れます。公開日は YouTube の RSS から取ります。プレイヤーでは「Official Music Video」にだけ入ります
  - 新しい動画（ライブ映像以外）は、1 回に 10 本まで動画ごとの情報を取り、概要欄に「- MusicVideo」の行があれば MV、なければ MV にしません（再生リスト・タイトルより優先。結果は `data/youtube.json` の `desc_mv` に残ります）。YouTube に止められて取れなかった動画は、再生リスト・タイトルで判定します。タイトルが「yosugala - 曲名」の形でない MV は、「」の中を曲名にします

### 手で直す

- `data/catalog.json` を直したら `python3 tools/update_catalog.py --offline` を実行してください。YouTube には接続せず、計算で出す値と案内ページ（`s/`）を作り直します
- 曲の開始・終了（フルライブの1曲目の SE、曲のあとの MC・写真撮影など）とタイトルは、ライブラリ編集ツール `editor.html`（プレーヤーのタイトル行の右端のギアから開けます。スマホでも使えます）で全曲を再生しながら、元のチャプターの位置・今の設定と見比べて調整できます。調整した値はそのブラウザのプレーヤーにだけすぐ反映され（タイトル行に「調整値で再生中」と出ます）、「書き出す」で調整した曲だけをまとめた JSON ファイルができます。`python3 tools/apply_edits.py 書き出したファイル.json` で `data/catalog.json` に書き込むと、全員のプレーヤーに反映されます。範囲やタイトルを直しても曲 ID は変わりません
- 公演の中の曲順は、フルライブ映像があればチャプターの順です（単独映像は、同じ曲のチャプターのすぐあとに入ります）。フルライブ映像がない公演は `lives` のセットリストの曲順で決めます。同じ曲の中は公演日の古い順に並びます（公開日 `published` もデータに入っていますが、画面には出しません）
- 同じ公演・同じ曲にフルライブ映像のチャプターと単独映像があるときは、どちらもプレイヤーに表示します（チャプターには、重なっている単独映像の動画 ID を `duplicate_of` に書きます）
- MC（メンバーが話している区間）は `type: "mc"` の項目です。プレイヤーの「ライブMC集」にだけ入ります（曲の一覧・公演のプレイリストには入りません）。名前は「MC① (次の曲のまえ)」の形です
- 新しい MC の候補は `python3 tools/make_candidates.py > candidates.json` で作り、ライブラリ編集ツールの「候補を読み込む」で要不要・名前・範囲を確かめて書き出します。`apply_edits.py` で書き込むと、書き出しの `add` が新しい曲 ID 付きで `items` に入ります

## 新しいライブ動画の曲・MC の候補を作る（手元の PC で）

新しいライブ動画が出たら、手元の PC（macOS など）で候補を作り、ライブラリ編集ツールで確かめます。

```bash
pip install numpy faster-whisper            # 初めてのときだけ（音声を分析する場合）
python3 tools/find_candidates.py --audio 動画ID > candidates.json
```

- 曲の候補は、チャプター → 概要欄のタイムスタンプ（「00:00 曲名」の行）→ 音声の「音楽」の区間の順に、使えるものから作ります（音声だけのときは名前が「（曲名なし）」）
- `--audio` を付けると音声をダウンロードして分析し、曲の範囲を音楽が鳴っているところに縮め（頭の SE・終わりの歓声や MC を外す）、曲と曲の間で話し声が多いところを MC の候補にして、文字起こし（`text`）を付けます。文字起こしは faster-whisper（既定のモデルは `small`。`--model` で変更、`--no-text` で省略）
- すでにカタログにある曲・MC と、`talk_skips` の時間帯は候補にしません（`--all` で全部）
- YouTube のボット確認で止められたら `--cookies-from-browser safari`（または `chrome`）を付けます
- 動画の情報・音声・分析結果・文字起こしは `~/.cache/yosugala-candidates/動画ID/` に残り、次からは使い回します（`--work` で場所を変更）。リポジトリには入れません
- できた `candidates.json` は、ライブラリ編集ツールの「候補を読み込む」で要不要・種類・名前・範囲を直して書き出します。MC は書き出しの `add` を `talks` に入れます
- しきい値は `--set 名前=値` で変えられます（名前は `tools/find_candidates.py` の `PARAMS`）

しきい値は、今のカタログを正解として比べて決めます。

```bash
python3 tools/eval_candidates.py --audio          # カタログのフルライブ映像すべてで、候補とカタログ（曲の範囲・MC）を比べる
python3 tools/eval_candidates.py --audio -v --set mc_talk_ratio=0.3   # しきい値を変えて、外れたものを一つずつ見る
python3 tools/eval_candidates.py --audio --no-chapters                 # チャプターがない動画で、音声だけで曲を探したときの出来
```

曲・MC ごとに、見つけ漏れ・余計な候補の数と、開始・終了のずれ（秒）を出します。`--audio` を付けないと、チャプターだけで作ったときの出来（比べる基準）になります。
