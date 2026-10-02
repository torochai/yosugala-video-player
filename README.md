# yosugala video player

yosugala official の公式ライブ映像（YouTube）から好きな曲だけを集めて、自分だけのセットリストで続けて再生できる非公式のファンメイドプレイヤーです。フルライブ映像の中の1曲だけを切り出して再生することもできます。

https://torochai.github.io/yosugala-video-player/

- 曲ごとに開始・終了時刻を指定して、フルライブ映像から1曲だけ再生できます
- プレイリストの作成・編集（追加・並べ替え・削除）、複数プレイリスト
- 共有リンク、書き出し / 読み込み
- リピート（全曲 / 1曲）、全画面再生

映像はすべて YouTube の埋め込みで公式動画を再生しています。映像・楽曲の権利は yosugala および各権利者に帰属します。
このページは yosugala 公式とは関係ありません。

## ライブ映像の一覧（catalog.json）の更新

プレイヤーのライブラリにある次のプレイリストは `catalog.json` から作られます。

- すべてのライブ映像 - 曲順（曲名順。同じ曲の中は公演日の古い順）
- すべてのライブ映像 - 公演日順（公演日の古い順。同じ公演の中はセットリスト順）
- 公演ごとのプレイリスト「YYYY.MM.DD「公演名」」（新しい公演が上。曲はセットリスト順）

曲の行には「YYYY.MM.DD「公演名」 @ 会場名」と表示します。

公式チャンネルに新しいライブ映像が出たら、次のコマンドで更新して push してください（yt-dlp が必要です）。

```bash
python3 tools/update_catalog.py
git add catalog.json tools/video_cache.json && git commit -m "Update catalog" && git push
```

- 単独の「Official Live Video」は1曲として、フルライブ映像はチャプターで曲ごとに分けて登録します（MC・SE などは除外）
- 一度取得した動画の情報は `tools/video_cache.json` に保存され、次回からは新しい動画だけを取得します
- YouTube のボット確認で止められたときは `python3 tools/update_catalog.py --cookies-from-browser chrome` で実行してください
- 曲名の表記ゆれ、ライブ名の表示、終了時刻の調整、除外は `tools/catalog_overrides.json` で直せます
- タイトルに公演名がない単独映像は `catalog_overrides.json` の `video_lives`（動画ID → ライブ名）で公演を指定します
- 会場名は `catalog_overrides.json` の `live_venues`（ライブ名 → 会場名）に書きます
- 公演の中の曲順は、フルライブ映像があればチャプターの順です（単独映像は、非表示にした同じ曲のチャプターの位置に入ります）。フルライブ映像がない公演は `catalog_overrides.json` の `setlists`（ライブ名 → 曲名の並び。LiveFans などのセットリストから）で決めます
- 補正ファイルだけを直したときは `python3 tools/update_catalog.py --offline` で、YouTube に接続せずに `video_cache.json` から作り直せます
- 公演日はタイトルの日付から取ります。タイトルに日付がない公演は `catalog_overrides.json` の `live_dates`（ライブ名 → 公演日）に書いてください。同じ曲の中は公演日の古い順に並びます（公開日 `published` もデータに入っていますが、画面には出しません）
- 同じ公演・同じ曲の単独映像があるフルライブのチャプターは、`catalog.json` に `"hidden": true`（理由 `hidden_reason`、重なっている単独映像 `duplicate_of`）の印を付けてプレイヤーでは表示しません。表示に戻すときは `catalog_overrides.json` の `prefer_single_over_full` を `false` にして再実行します
