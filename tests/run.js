#!/usr/bin/env node
// yosugala video player のテスト（Playwright の Chromium で、ページを実際に動かして確かめる）
//
// 使い方（リポジトリのフォルダで）:
//   NODE_PATH=$(npm root -g) node tests/run.js            # 全部
//   NODE_PATH=$(npm root -g) node tests/run.js share io   # 名前で絞り込み（下の TESTS のキー）
// 必要なもの: Node.js、playwright（npm install -g playwright）、python3（テスト用のサーバー）
// Chromium は CHROMIUM_PATH（なければ /opt/pw-browsers/chromium、それもなければ Playwright の既定）を使う。
// YouTube の動画はテストでは再生しないので、iframe_api を偽のプレイヤー（STUB）に差し替える。
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const PORT = 8790 + Math.floor(Math.random() * 100);
const BASE = `http://localhost:${PORT}/`;
const CHROMIUM = process.env.CHROMIUM_PATH || (fs.existsSync('/opt/pw-browsers/chromium') ? '/opt/pw-browsers/chromium' : undefined);

// 偽の YouTube プレイヤー: 読み込んだ動画と開始秒を window.__loads に記録する。再生位置は window.__t で動かせる
const STUB = `window.YT = { PlayerState: { ENDED: 0, PLAYING: 1, PAUSED: 2, BUFFERING: 3, CUED: 5 },
  Player: function (el, cfg) { window.__cfg = cfg; const self = this; let vid = cfg.videoId, t = (cfg.playerVars || {}).start || 0, st = 5;
    window.__loads = []; const ev = cfg.events || {}, fire = (d) => ev.onStateChange && ev.onStateChange({ data: d });
    Object.assign(this, { getCurrentTime: () => window.__t ?? t, getDuration: () => 600, getVideoData: () => ({ video_id: vid }),
      getPlayerState: () => st, playVideo() { st = 1; fire(1); }, pauseVideo() { st = 2; },
      loadVideoById(o) { vid = o.videoId; t = o.startSeconds; window.__loads.push(o); st = 1; fire(1); },
      cueVideoById(o) { vid = o.videoId; t = o.startSeconds; st = 5; }, seekTo(s) { t = s; window.__t = undefined; }, setVolume() {}, mute() {}, unMute() {},
      isMuted: () => false, unloadModule() {}, loadModule() {}, setOption() {}, getIframe: () => document.createElement('iframe') });
    setTimeout(() => ev.onReady && ev.onReady({ target: self }), 50); } };
  window.onYouTubeIframeAPIReady && window.onYouTubeIframeAPIReady();`;
const IPHONE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1';
const KEY = 'yosugala-live-selection-v1';
const LIVE_0725 = '__live__:2025-07-25|tour2025 FINAL';

let browser, failed = 0, passed = 0;
const errors = [];
function ok(label, cond, detail = '') {
  if (cond) passed++; else failed++;
  console.log(`${cond ? '  OK' : '  NG'}  ${label}${!cond && detail ? `  … ${typeof detail === 'string' ? detail : JSON.stringify(detail)}` : ''}`);
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// 新しいページ（毎回まっさらなブラウザ）。seed: 開く前に入れておく localStorage
async function open(url = '', { width = 1280, height = 900, mobile = false, ua, screen, seed } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height }, isMobile: mobile, hasTouch: mobile, userAgent: ua, screen });
  await ctx.route(/iframe_api/, (r) => r.fulfill({ contentType: 'text/javascript', body: STUB }));
  await ctx.route(/ytimg|fonts\.g|google\.|youtube\.com\/(?!iframe_api)|x\.com/, (r) => r.abort());
  await ctx.addInitScript((seed) => {
    window.__opened = []; window.open = (u) => { window.__opened.push(u); return null; };
    if (seed && !sessionStorage.getItem('__seeded')) { sessionStorage.setItem('__seeded', '1'); for (const [k, v] of Object.entries(seed)) localStorage.setItem(k, JSON.stringify(v)); }
  }, seed);
  const p = await ctx.newPage();
  p.on('pageerror', (e) => errors.push(`${url}: ${e.message}`));
  await p.goto(BASE + url); await p.waitForFunction(() => (typeof catalog !== 'undefined' && catalog) || document.title.includes('調整ツール'), null, { timeout: 15000 });
  await wait(300);
  p.ctx = ctx;
  return p;
}
const close = (p) => p.ctx.close();
const switchPl = (p, id) => p.evaluate((id) => { const s = $('plSelect'); s.value = id; s.dispatchEvent(new Event('change')); }, id);
const xText = async (p, btn) => { await p.click(btn); return new URL(await p.evaluate(() => window.__opened.at(-1))).searchParams.get('text'); };
const copied = async (p, btn) => { await p.evaluate(() => { navigator.clipboard.writeText = async (t) => { window.__copied = t; }; }); await p.click(btn); return p.evaluate(() => window.__copied); };

const TESTS = {
  // 起動: トロ's セレクション、保存の形、カタログのプレイリスト
  async startup() {
    const p = await open();
    const r = await p.evaluate(() => ({ name: pl().name, n: items().length, first: items()[0].title, row: items()[0].id, sid: items()[0].sid, rows: $('list').children.length,
      lib: catalogPls.length, stored: JSON.parse(localStorage.getItem('yosugala-live-selection-v1')).playlists[0].items[0] }));
    ok('トロ\'s セレクション（16曲、1曲目 indigo）', r.name === "トロ's セレクション" && r.n === 16 && r.first === 'indigo' && r.rows === 16, r);
    ok('行 ID は「toro:曲 ID」', r.row === 'toro:45' && r.sid === 45, r);
    ok('ブラウザには曲 ID だけ保存', JSON.stringify(r.stored) === '{"id":"toro:45","sid":45}', r.stored);
    // すべてのライブ映像には、同じ公演・同じ曲のフルライブ映像のチャプターと単独映像の両方が出る。公演のプレイリストはフルライブ映像のチャプターで
    const both = await p.evaluate(() => {
      const all = catalogPls.find((q) => q.id === CATALOG_ID).all.filter((x) => infoOf(x).date === '2024-02-18' && x.title === 'ソラノナミダ').map((x) => infoOf(x).kind);
      const live = catalogPls.find((q) => q.id === '__live__:2024-02-18|progress the night -LIQUIDROOM-').all.filter((x) => x.title === 'ソラノナミダ').map((x) => infoOf(x).kind);
      return { all, live, total: catalogPls.find((q) => q.id === CATALOG_ID).all.length, catalog: catalog.songs.length };
    });
    ok('すべてのライブ映像にはフルライブ映像のチャプターと単独映像の両方、公演のプレイリストはフルライブ映像のチャプター',
      both.all.sort().join() === 'full,single' && both.live.join() === 'full' && both.total === both.catalog, both);
    ok('カタログのプレイリストができる', r.lib > 5, r.lib);
    ok('URL で曲を追加する画面はない', await p.evaluate(() => !document.getElementById('addSong') && !document.getElementById('songDlg')));
    await close(p);
    const q = await open('', { seed: { [KEY]: { current: 'old', lastPlayed: 'old', playlists: [{ id: 'old', name: '前の形式', items: [{ id: 'a', vid: 'Tv7KrUG9C0Q', start: 559, title: 'x' }] }] } } });
    ok('前の形式で保存されたプレイリストは曲なし（エラーにならない）', await q.evaluate(() => state.playlists.find((x) => x.id === 'old').items.length === 0));
    await close(q);
  },

  // 自分のプレイリスト: 作成・追加・並べ替え・削除・再読み込み後も残る、編集中のボタン
  async playlists() {
    const p = await open('#lib=2025-07-25');
    await p.evaluate(() => { createPlaylist(); }); await wait(150); await p.fill('#askInput', 'テスト'); await p.click('#askOk'); await wait(200);
    await switchPl(p, LIVE_0725);
    await p.evaluate(() => openAdd(items().slice(0, 3))); await wait(150);
    await p.evaluate(() => [...$('addTargets').children].find((x) => x.textContent.startsWith('テスト')).click());
    const id = await p.evaluate(() => state.playlists.find((x) => x.name === 'テスト').id);
    await switchPl(p, id); await p.evaluate(() => { editing = true; renderAll(); move(0, 2); });
    const titles = await p.evaluate(() => items().map((it) => it.title));
    await p.evaluate(() => { removeSong(items()[0].id); }); await wait(150); await p.click('#askOk'); await wait(200);
    await p.reload(); await p.waitForFunction(() => (typeof catalog !== 'undefined' && catalog)); await wait(300);
    const after = await p.evaluate(() => state.playlists.find((x) => x.name === 'テスト').items.map((it) => it.title));
    ok('追加・並べ替え・削除が再読み込み後も残る', after.join() === titles.slice(1).join(), { titles, after });
    await switchPl(p, id);
    const vis = () => p.evaluate(() => [...document.querySelectorAll('.pactions button')].filter((b) => !b.hidden && b.offsetParent).map((b) => b.textContent.trim()).join(' / '));
    ok('自分のプレイリストのボタンは 選択・編集・複製・共有', await vis() === '選択 / 編集 / 複製 / 共有', await vis());
    await p.evaluate(() => { editing = true; renderAll(); });
    ok('編集中は「完了」だけ', await vis() === '完了', await vis());
    await p.evaluate(() => { editing = false; renderAll(); }); await switchPl(p, 'builtin-toro');
    ok('ライブラリのボタンは 選択・複製・共有（＋情報）', /選択 \/ 複製 \/ 共有$/.test(await vis()), await vis());
    await p.click('#dupEdit'); await wait(200);
    ok('ライブラリを複製すると自分のプレイリストになる', await p.evaluate(() => !pl().readonly && items().length === 16 && items()[0].sid === 45 && items()[0].id !== 'toro:45'));
    await close(p);
  },

  // 書き出し / 読み込み（JSON）
  async io() {
    const p = await open();
    await p.evaluate(() => { state.playlists.push({ id: 'mine', name: 'マイ', author: '', desc: '', items: [] }); switchTo('mine'); editing = true; renderAll(); });
    await p.click('#plIO'); await p.fill('#ioText', JSON.stringify({ name: '読み込み', songs: [999] })); await p.click('#ioImport'); await wait(150);
    ok('カタログにない曲 ID はエラー', /999/.test(await p.evaluate(() => $('ioErr').textContent)));
    await p.fill('#ioText', JSON.stringify({ name: '読み込み', author: 'トロ', desc: 'd', songs: [45, 53] })); await p.click('#ioImport'); await wait(200);
    ok('空のプレイリストには確認なしで読み込む', await p.evaluate(() => !$('askDlg').open && pl().id === 'mine' && pl().name === '読み込み' && items().length === 2));
    await p.click('#plIO');
    const json = JSON.parse(await p.inputValue('#ioText'));
    ok('書き出しの形は { name, author, desc, songs }', Object.keys(json).join() === 'name,author,desc,songs' && json.songs.join() === '45,53', json);
    await p.fill('#ioText', JSON.stringify({ name: '上書き', songs: [76] })); await p.click('#ioImport'); await wait(150);
    ok('曲が入っていれば上書きの確認が出る', await p.evaluate(() => $('askDlg').open));
    await p.click('#askCancel'); await wait(150);
    ok('キャンセルなら変わらない', await p.evaluate(() => pl().name === '読み込み' && items().length === 2));
    await p.click('#ioImport'); await wait(150); await p.click('#askOk'); await wait(200);
    ok('OK なら上書き（ID はそのまま）', await p.evaluate(() => pl().id === 'mine' && pl().name === '上書き' && items()[0].title === 'コノユビトマレ'));
    await close(p);
  },

  // 共有: プレイリストのリンク、共有リンクで開く、X への共有、曲の案内ページ
  async share() {
    const p = await open('#lib=2025-07-25');
    ok('ライブラリの共有リンクは #lib=', (await copied(p, '#plShare')).endsWith('#lib=2025-07-25'));
    await p.evaluate(() => { state.playlists.push({ id: 'mine', name: 'マイ', author: 'トロ', desc: '', items: [songRow(45), songRow(53)] }); switchTo('mine'); });
    const link = await copied(p, '#plShare');
    ok('自分のプレイリストの共有リンクは #pl=曲ID…&t=名前&a=作成者', /#pl=45\.53&t=%E3%83%9E%E3%82%A4&a=%E3%83%88%E3%83%AD$/.test(link), link);
    ok('X: プレイリストを共有', (await xText(p, '#plXShare')) === `📋 マイ - yosugalaライブ映像プレイリスト (2曲) by トロ #yosugala ${link}`, await xText(p, '#plXShare'));
    await switchPl(p, LIVE_0725);
    ok('X: プレイリストを共有（名前が 」 で終わるときは - の前にスペースなし）', /^📋 2025\.07\.25「tour2025 FINAL」- yosugalaライブ映像プレイリスト \(24曲\) #yosugala http:\/\/localhost:\d+\/#lib=2025-07-25$/.test(await xText(p, '#plXShare')), await xText(p, '#plXShare'));
    await switchPl(p, '__live__:2024-11-01|tour2024 aki「春に廻れなかった場所編」Final'); await p.evaluate(() => playIndex(1)); await wait(300);
    const t = await xText(p, '#songShare');
    ok('X: 曲を共有', /^🎥 sailing!! ／ yosugala \| 2024\.11\.01「tour2024 aki『春に廻れなかった場所編』Final」@ EX THEATER ROPPONGI #yosugala http:\/\/localhost:\d+\/s\/57\.html\?lib=2024-11-01$/.test(t), t);
    await p.evaluate(() => { state.playlists.push({ id: 'empty', name: '空', author: '', desc: '', items: [] }); switchTo('empty'); });
    ok('空のプレイリストでは X ボタンを出さない', await p.evaluate(() => $('plXShare').hidden && $('songShare').hidden));
    await close(p);

    // 共有リンクで開く: 保存しなくても再生でき、「保存しない」は案内を閉じるだけ
    const q = await open(link.replace(/^https?:\/\/[^/]+\//, ''));
    ok('共有リンクで開くと案内が出る', await q.evaluate(() => !$('shareBanner').hidden && pl().name === 'マイ' && items().length === 2));
    await q.click('#start'); await wait(500);
    ok('保存しなくても再生できる', await q.evaluate(() => started && $('nowTitle').textContent === 'indigo'));
    await q.click('#shareDismiss'); await wait(150);
    ok('「保存しない」は案内を閉じるだけ（プレイリスト・URL はそのまま、保存しない）', await q.evaluate(() => $('shareBanner').hidden && pl().name === 'マイ'
      && location.hash.startsWith('#pl=') && !(localStorage.getItem('yosugala-live-selection-v1') || '').includes('"マイ"')));
    await switchPl(q, 'builtin-toro'); await q.evaluate(() => switchTo(shared.id));
    ok('ほかに切り替えても戻れる', await q.evaluate(() => pl().name === 'マイ'));
    await q.reload(); await q.waitForFunction(() => (typeof catalog !== 'undefined' && catalog)); await wait(300); await q.click('#shareSave'); await wait(150);
    ok('「マイライブラリに保存」で保存され、URL は元に戻る', await q.evaluate(() => (localStorage.getItem('yosugala-live-selection-v1') || '').includes('"マイ"') && !location.hash));
    await close(q);

    // 曲の案内ページ s/曲ID.html → プレーヤーのその曲
    for (const [u, want] of [['s/57.html?lib=2024-11-01', (r) => r.title === 'sailing!!' && r.pl.includes('2024-11-01')],
                             ['s/104.html?lib=toro', (r) => r.title === 'きっかけ' && r.pl === 'builtin-toro'],
                             ['s/108.html', (r) => r.title === 'エスカレート' && r.live]]) {
      const s = await open(u);
      const r = await s.evaluate(() => ({ title: $('nowTitle').textContent, pl: pl().id, live: !!pl().live, url: location.search + location.hash }));
      ok(`曲の案内ページ ${u}`, want(r) && r.url === '', r);
      await close(s);
    }
    const page = fs.readFileSync(path.join(ROOT, 's/57.html'), 'utf8');
    ok('案内ページに X のカード用の情報', page.includes('og:image" content="https://i.ytimg.com/vi/EiobVwTprto/') && page.includes('♫ sailing!! ／ yosugala'));
  },

  // 再生: 続きから再生、次の曲・最後の曲、リピート、時間表示でボタンが動かない
  async playback() {
    const p = await open('#lib=2025-07-25');
    await p.evaluate(() => playIndex(2)); await wait(600);
    const it = await p.evaluate(() => items()[2]);
    await p.evaluate((s) => { window.__t = s + 83; saveResume(true); }, it.start); await wait(100);
    await p.reload(); await p.waitForFunction(() => (typeof catalog !== 'undefined' && catalog)); await wait(400);
    ok('続きから再生（前回の位置を覚えている）', await p.evaluate(() => curIndex() === 2 && /前回の続き（1:23）/.test($('msg').textContent)), await p.evaluate(() => $('msg').textContent));
    await p.click('#start'); await wait(500);
    ok('PLAY で続きの秒から始まる', await p.evaluate((s) => window.__cfg.playerVars.start === s + 83, it.start), await p.evaluate(() => window.__cfg.playerVars));
    await p.evaluate(() => { window.__t = undefined; setRepeat('off'); playIndex(items().length - 1); }); await wait(300);
    ok('最後の曲では「次の曲」「最後の曲」を押せない', await p.evaluate(() => $('next').disabled && $('last').disabled));
    await p.evaluate(() => setRepeat('all')); await wait(100);
    ok('リピート（全曲）なら「次の曲」で1曲目へ', await p.evaluate(() => { const d = $('next').disabled; next(false); return !d && curIndex() === 0; }));
    await p.click('#last'); await wait(200);
    ok('「最後の曲から再生」', await p.evaluate(() => curIndex() === items().length - 1));
    await p.click('#first'); await wait(200);
    ok('「最初の曲から再生」', await p.evaluate(() => curIndex() === 0));
    const pos = await p.evaluate(async () => { const r = []; for (const t of ['0:00', '1:11', '4:44', '9:59']) { $('tcur').textContent = t; await new Promise((x) => requestAnimationFrame(x));
      r.push(['first', 'prev', 'pp', 'next', 'last', 'repeat', 'fs'].map((id) => Math.round($(id).getBoundingClientRect().left)).join()); } return new Set(r).size; });
    ok('時間の表示が変わってもボタンが動かない', pos === 1);
    await close(p);
  },

  // 曲名の下のボタン: この公演の続き・別公演の同じ曲・戻る
  async nowacts() {
    const p = await open('#lib=toro');
    await p.click('#start'); await wait(500);
    const st = () => p.evaluate(() => ({ pl: pl().id, i: curIndex(), title: $('nowTitle').textContent, live: infoOf(items()[curIndex()]).live, started, loads: window.__loads.length,
      a: !$('playLive').hidden, b: !$('playOther').hidden }));
    const s0 = await st();
    ok('トロ\'s セレクションでは2つとも出る', s0.a && s0.b, s0);
    await p.click('#playLive'); await wait(300);
    const s1 = await st();
    ok('この公演の続きを再生: 止めずに公演のプレイリストの同じ曲へ', s1.pl.startsWith('__live__:2024-02-18') && s1.title === 'indigo' && s1.started && s1.loads === s0.loads && !s1.a, s1);
    await p.evaluate(() => next(true)); await wait(300);
    ok('曲が終わるとセットリストの次の曲へ', await p.evaluate((i) => curIndex() === i + 1, s1.i));
    const s1b = await st();
    await p.click('#playOther'); await wait(300);
    const s2 = await st();
    ok('別公演の同じ曲: 止めずに、曲名で絞った一覧の今の曲へ', s2.pl === '__catalog__' && s2.title === s1b.title && s2.live === s1b.live && s2.started
      && s2.loads === s1b.loads && s2.b && await p.evaluate((t) => catQuery === t && items().length > 1 && items().every((x) => x.title === t), s1b.title), s2);
    await p.evaluate(() => next(true)); await wait(300);
    const s2b = await st();
    ok('曲が終わると別の公演の同じ曲へ', s2b.title === s1b.title && s2b.live !== s1b.live && s2b.loads === s1b.loads + 1, s2b);
    await p.click('#playOther'); await wait(300);
    const s2c = await st();
    ok('一覧に移ったあとにもう一度押すと、次の公演の同じ曲を再生', s2c.pl === '__catalog__' && s2c.i === s2b.i + 1 && s2c.title === s1b.title && s2c.loads === s2b.loads + 1, s2c);
    const n = await p.evaluate(() => items().length);
    await p.evaluate(() => { setRepeat('off'); playIndex(items().length - 1); }); await wait(200);
    ok('一覧の最後でも「次の曲」を押せる', await p.evaluate(() => !$('next').disabled));
    await p.evaluate(() => next(true)); await wait(200);
    ok('一覧の最後の曲が終わると一番上へ（リピートがオフでも）', await p.evaluate(() => curIndex() === 0 && started));
    await p.evaluate(() => playIndex(items().length - 1)); await wait(200);
    await p.click('#playOther'); await wait(200);
    ok('一覧の最後で押すと一番上へ', await p.evaluate(() => curIndex() === 0), n);
    await p.evaluate(() => setRepeat('one')); await p.click('#playOther'); await wait(200);
    ok('リピート（1曲）でも押すと次の公演の同じ曲へ', await p.evaluate(() => curIndex() === 1));
    await p.evaluate(() => next(true)); await wait(200);
    ok('リピート（1曲）でも曲が終わると次の公演の同じ曲へ', await p.evaluate(() => curIndex() === 2));
    // 同じ公演のフルライブ版と単独映像は飛ばし、次の公演にどちらもあるときは単独映像へ（ソラノナミダ: 2024.02.18 は両方ある）
    const hop = await p.evaluate(() => {
      switchTo(CATALOG_ID); catQuery = 'ソラノナミダ'; $('catSearch').value = catQuery; renderAll();
      const key = (x) => `${infoOf(x).date}:${infoOf(x).kind}`, seq = [];
      playIndex(0); seq.push(key(items()[curIndex()]));
      for (let k = 0; k < 4; k++) { next(true); seq.push(key(items()[curIndex()])); }
      $('playOther').click(); seq.push(key(items()[curIndex()]));
      return seq;
    });
    ok('同じ曲名の一覧では同じ公演を飛ばし、一周して戻った公演は単独映像', hop.join() ===
      ['2024-02-18:full', '2024-11-01:full', '2025-02-08:full', '2024-02-18:single', '2024-11-01:full', '2025-02-08:full'].join(), hop);
    await p.evaluate(() => setRepeat('off'));
    // 戻るは押した回数ぶん。ここでは途中のボタンの分を捨てて、最初の2回（公演の続き・別公演の同じ曲）だけで確かめる
    await p.evaluate(() => { backStack.length = 2; showNow(); });
    ok('戻るボタンが出る', await p.evaluate(() => !$('playBack').hidden && backStack.length === 2));
    await p.click('#playBack'); await wait(200);
    ok('戻る1回目: 公演のプレイリストの曲へ（絞り込みも元に戻る）', await p.evaluate((s) => pl().id === s.pl && curIndex() === s.i + 1 && catQuery === '', s1));
    await p.click('#playBack'); await wait(200);
    ok('戻る2回目: 最初のプレイリストへ。戻り切るとボタンは消える', await p.evaluate(() => pl().id === 'builtin-toro' && curIndex() === 0 && $('playBack').hidden));
    await p.evaluate(() => { const i = 2; playIndex(i); }); await wait(200);
    const left = await p.evaluate(() => { const it = items()[curIndex()]; window.__t = it.start + 70; return it.start + 70; });
    await p.click('#playOther'); await wait(200); await p.evaluate(() => { window.__t = undefined; next(true); }); await wait(200);
    await p.click('#playBack'); await wait(200);
    ok('違う曲に戻るときは離れた位置から再生', await p.evaluate((t) => window.__loads.at(-1).startSeconds === t, left), await p.evaluate(() => window.__loads.at(-1)));
    await p.click('#playOther'); await wait(200); await switchPl(p, 'builtin-toro');
    ok('メニューで自分で切り替えると戻る記録は消える', await p.evaluate(() => backStack.length === 0 && $('playBack').hidden));
    await switchPl(p, LIVE_0725); await p.evaluate(() => playIndex(items().findIndex((x) => x.title === 'きっかけ'))); await wait(200);
    ok('公演のプレイリスト・ほかの公演にない曲では出さない', await p.evaluate(() => $('nowActs').hidden));
    await close(p);
  },

  // 画面幅ごとのレイアウト
  async layout() {
    for (const [w, h, rows] of [[414, 896, 1], [390, 844, 1], [360, 740, 1], [820, 1180, 1], [1280, 900, 1]]) {
      const p = await open('#lib=2025-07-25', { width: w, height: h, mobile: w < 900 });
      const r = await p.evaluate(() => new Set([...document.querySelectorAll('.bar > *')].filter((e) => e.offsetParent && e.id !== 'seek')
        .map((e) => Math.round((e.getBoundingClientRect().top + e.getBoundingClientRect().bottom) / 2))).size);
      ok(`操作バーが ${w}px で1段`, r === rows, r);
      ok(`${w}px で横スクロールが出ない`, await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await close(p);
    }
    // 曲名の下の3つのボタン（この公演の続き・別公演の同じ曲・戻る）が1行に収まる
    for (const [w, h] of [[320, 568], [390, 844], [1280, 900]]) {
      const p = await open('#lib=toro', { width: w, height: h, mobile: w < 900 });
      await p.click('#start'); await wait(400); await p.click('#playLive'); await wait(200); await p.click('#playOther'); await wait(200);
      const r = await p.evaluate(() => { const b = ['playLive', 'playOther', 'playBack'].map((id) => $(id).getBoundingClientRect());
        return { shown: b.every((x) => x.width > 0), rows: new Set(b.map((x) => Math.round(x.top))).size, back: $('playBack').textContent.trim() }; });
      ok(`${w}px で曲名の下のボタンと「戻る」が1行`, r.shown && r.rows === 1 && r.back === '戻る', r);
      await close(p);
    }
    for (const [w, h, min] of [[1600, 900, 850], [1920, 1080, 1150]]) {
      const p = await open('#lib=2025-07-25', { width: w, height: h });
      const r = await p.evaluate(() => ({ video: Math.round(document.querySelector('.screen').getBoundingClientRect().width), nowBottom: document.querySelector('.now').getBoundingClientRect().bottom, ih: innerHeight }));
      ok(`PC ${w}×${h}: 動画が広がり、曲名・キャプション・その下のボタンが画面に収まる`, r.video >= min && r.nowBottom <= r.ih, r);
      await close(p);
    }
    const ip = await open('', { width: 814, height: 430, mobile: true, ua: IPHONE_UA, screen: { width: 430, height: 932 } });
    ok('iPhone（大きい画面）の横向きはリストを右に並べる', await ip.evaluate(() => document.querySelector('meta[name="viewport"]').content === 'width=932' && matchMedia('(min-width: 901px)').matches));
    await close(ip);
    const t = await open('#pl=45.53&t=x');
    await t.click('h1 a.home'); await t.waitForFunction(() => (typeof catalog !== 'undefined' && catalog) && !location.hash); await wait(300);
    ok('左上のタイトルでトップの URL に戻る', await t.evaluate(() => location.href.endsWith('/') && !location.hash && $('shareBanner').hidden));
    await close(t);
  },

  // 再生範囲調整ツール（tools/trim.html）と、その値のプレーヤーへの反映
  async trim() {
    const p = await open('tools/trim.html');
    await p.waitForFunction(() => $('list').children.length > 0);
    const all = JSON.parse(fs.readFileSync(path.join(ROOT, 'catalog.json'), 'utf8')).songs;
    ok('プレーヤーのタイトル（プレーヤーへのリンク）が出る', await p.evaluate(() => document.querySelector('.brand a').getAttribute('href') === '../'
      && document.querySelector('.brand').textContent.includes('yosugala')));
    ok('一覧は初めは名前順（catalog.json の曲名順と同じ）', await p.evaluate((ids) => [...$('list').children].map((li) => li.song.id).join() === ids.join()
      && document.querySelector('[data-order="name"]').getAttribute('aria-pressed') === 'true', all.map((s) => s.id)));
    await p.evaluate(() => { select(songs[songs.length - 1]); $('list').scrollTop = 0; });
    await p.click('[data-order="id"]');
    ok('並び順を変えると、再生中の曲が見える位置へ', await p.evaluate(() => { const r = $('list').querySelector('li.sel').getBoundingClientRect(), o = $('list').getBoundingClientRect();
      return $('list').scrollTop > 0 && r.top >= o.top && r.bottom <= o.bottom; }));
    ok('ID順に切り替えられる', await p.evaluate(() => { const ids = [...$('list').children].map((li) => li.song.id); return ids.every((x, i) => !i || ids[i - 1] < x); }));
    await p.click('[data-order="date"]');
    ok('公演日順に切り替えられる', await p.evaluate(() => { const d = [...$('list').children].map((li) => li.song.date || '9999'); return d.every((x, i) => !i || d[i - 1] <= x); }));
    await p.reload(); await p.waitForFunction(() => $('list').children.length > 0);
    ok('選んだ並び順はブラウザに残る', await p.evaluate(() => document.querySelector('[data-order="date"]').getAttribute('aria-pressed') === 'true'));
    await p.click('[data-order="name"]');
    ok('一覧に全曲（単独映像もフルライブ映像のチャプターも）が並ぶ', await p.evaluate(() => $('list').children.length) === all.length);
    // 開始・終了を直してある曲: 元のチャプターと今の設定が並ぶ
    const fixed = all.find((s) => s.kind === 'full' && 'chapter_end' in s && 'chapter_start' in s);
    await p.evaluate((id) => select(songs.find((s) => s.id === id)), fixed.id); await wait(200);
    const t = await p.evaluate(() => ['oStart', 'cStart', 'vStart', 'oEnd', 'cEnd', 'vEnd'].map((id) => $(id).textContent));
    ok('元のチャプターの位置と今の設定の位置が出る', t[0] !== t[1] && t[1] === t[2] && t[3] !== t[4] && t[4] === t[5], t);
    ok('調整していなければ書き出すものはない', await p.evaluate(() => $('out').value === '' && $('download').disabled));
    await p.evaluate(() => { window.__t = cur.start + 2; }); await p.click('#setStart');
    await p.evaluate(() => { window.__t = cur.start + 200; });   // 操作バーの ±5秒・±1秒で再生位置を動かしてから「ここを終わりに」
    await p.click('.bar [data-seek="5"]'); await p.click('.bar [data-seek="-5"]'); await p.click('.bar [data-seek="1"]'); await p.click('#setEnd');
    const out = JSON.parse(await p.inputValue('#out')), k = Object.keys(out.segments);
    ok('操作バーの ±5秒・±1秒で位置を合わせられ、書き出しは調整した曲だけの segments（キーは 動画ID@元の開始秒、開始・終了とも）', k.length === 1 && k[0] === `${fixed.vid}@${fixed.chapter_start}`
      && out.segments[k[0]].start === fixed.start + 2 && out.segments[k[0]].end === fixed.start + 201, out);
    ok('一覧に「調整済み」', await p.evaluate(() => $('list').querySelector('li.sel .badge.changed').textContent === '調整済み'));
    // 単独映像も調整できる（元は 0 秒〜動画の最後）
    const single = all.find((s) => s.kind === 'single' && !('chapter_start' in s));
    await p.evaluate((id) => select(songs.find((s) => s.id === id)), single.id); await wait(200);
    ok('単独映像の元の位置は 0:00〜動画の最後', await p.evaluate(() => $('oStart').textContent === '0:00' && $('oEnd').textContent === '動画の最後'));
    await p.evaluate(() => { window.__t = 1.8; }); await wait(300);
    ok('秒の端数は切り捨てて表示する（YouTube のプレーヤーと同じ）', await p.evaluate(() => $('now').textContent === '0:01'));
    await p.click('#setStart');
    ok('操作バーの前の曲・次の曲で、一覧の前後の曲へ', await p.evaluate(() => { const vis = visible(), i = vis.indexOf(cur);
      $('nextSong').click(); const moved = cur === vis[i + 1]; $('prevSong').click(); return moved && cur === vis[i]; }));
    const dl = p.waitForEvent('download'); await p.click('#download');
    const file = await dl, body = JSON.parse(fs.readFileSync(await file.path(), 'utf8'));
    ok('ファイルに書き出せる（調整した2曲。「ここを開始に」は表示と同じ切り捨ての秒）', /^yosugala-segments-\d{8}-\d{4}\.json$/.test(file.suggestedFilename()) && Object.keys(body.segments).length === 2
      && body.segments[`${single.vid}@0`].start === 1 && body.segments[`${single.vid}@0`].end === null, body);
    await p.click('#reset');
    ok('この曲の調整を取り消すと書き出しから消える', Object.keys(JSON.parse(await p.inputValue('#out')).segments).length === 1);
    await p.reload(); await p.waitForFunction(() => $('list').children.length > 0);
    ok('調整はブラウザに残る', Object.keys(JSON.parse(await p.inputValue('#out')).segments).length === 1);
    await p.check('#onlyChanged');
    ok('「調整した曲だけ」で絞り込める', await p.evaluate(() => $('list').children.length) === 1);
    p.once('dialog', (d) => d.accept()); await p.click('#clearAll'); await wait(100);
    ok('「すべての調整をリセット」で調整がなくなる', await p.evaluate(() => $('out').value === '' && $('list').children.length === 0 && !Object.keys(JSON.parse(localStorage.getItem('yosugala-trim-v1'))).length));
    await close(p);
    // プレーヤー: 調整ツールの値で再生する（このブラウザだけ）。調整ツールで直すと、開いているプレーヤーにもすぐ反映
    const song = all.find((s) => s.kind === 'full' && !s.hidden && !('chapter_start' in s) && !('chapter_end' in s));
    const pp = await open('#lib=toro', { seed: { 'yosugala-trim-v1': { [`${song.vid}@${song.start}`]: { start: song.start + 3, end: song.end - 4 } } } });
    const range = () => pp.evaluate((id) => { const x = songById.get(id), it = catalogPls[0].all.find((i) => i.sid === id);
      return { s: x.start, e: x.end, len: x.len, is: it.start, ie: it.end, on: !$('trimOn').hidden }; }, song.id);
    ok('調整していない曲を再生しているときは「調整値で再生中」を出さない', await pp.evaluate((id) => items()[curIndex()].sid !== id && $('trimOn').hidden, song.id));
    await pp.evaluate((id) => { switchTo(CATALOG_ID); playIndex(items().findIndex((i) => i.sid === id)); }, song.id); await wait(200);
    const r1 = await range();
    ok('プレーヤーに調整ツールの値が反映され、調整した曲では「調整値で再生中」が出る', r1.s === song.start + 3 && r1.e === song.end - 4 && r1.len === song.len - 7 && r1.is === r1.s && r1.ie === r1.e && r1.on, r1);
    ok('タイトル行の右端に調整ツールへのギア（文字なし）', await pp.evaluate(() => { const g = document.querySelector('.herotools .gear'), h = document.querySelector('.hero').getBoundingClientRect();
      return g.getAttribute('href').startsWith('tools/trim.html') && !g.textContent.trim() && Math.abs(g.getBoundingClientRect().right - h.right) < 2
        && $('trimOn').getBoundingClientRect().right <= g.getBoundingClientRect().left; }));
    const tt = await pp.ctx.newPage(); await tt.goto(BASE + 'tools/trim.html'); await tt.waitForFunction(() => $('list').children.length > 0);
    await tt.evaluate((id) => select(songs.find((s) => s.id === id)), song.id); await wait(200); await tt.evaluate((e) => { window.__t = e; }, song.end + 1); await tt.click('#setEnd'); await wait(300);
    const r2 = await range();
    ok('調整ツールで直すと、開いているプレーヤーにすぐ反映', r2.e === song.end + 1 && r2.ie === r2.e, r2);
    await tt.click('#reset'); await wait(300);
    const r3 = await range();
    ok('調整を取り消すと元の範囲に戻り、「調整値で再生中」も消える', r3.s === song.start && r3.e === song.end && r3.len === song.len && !r3.on, r3);
    await tt.close();
    const sid = await pp.evaluate(() => { playIndex(5); return items()[5].sid; }); await wait(200);
    await pp.click('#trimGear'); await pp.waitForFunction(() => typeof cur !== 'undefined' && cur);
    ok('ギアから開くと、再生中の曲が選ばれている（一覧もその曲が見える位置に）', await pp.evaluate((sid) => { const li = document.querySelector('#list li.sel'), ol = $('list');
      const r = li.getBoundingClientRect(), o = ol.getBoundingClientRect();
      return cur.id === sid && li.song.id === sid && r.top >= o.top && r.bottom <= o.bottom; }, sid));
    ok('タイトル行の右端に「戻る」', await pp.evaluate(() => { const b = $('back').getBoundingClientRect(), h = document.querySelector('h1').getBoundingClientRect();
      return $('back').textContent.trim() === '戻る' && Math.abs(b.right - h.right) < 2 && b.top >= h.top && b.bottom <= h.bottom; }));
    await pp.click('#back'); await pp.waitForFunction(() => typeof catalog !== 'undefined' && catalog);
    ok('「戻る」でプレーヤーに戻る', await pp.evaluate(() => !location.pathname.includes('/tools/') && !!$('trimGear')));
    await close(pp);
    // カタログが調整値に追いついたら（同じ値になったら）、その曲は調整なしとして扱い、マークも出さない
    const caught = all.find((s) => s.kind === 'single' && 'chapter_start' in s);
    const pc = await open('#lib=toro', { seed: { 'yosugala-trim-v1': { [`${caught.vid}@${caught.chapter_start}`]: { start: caught.start, end: caught.end } } } });
    await pc.evaluate((id) => { switchTo(CATALOG_ID); playIndex(items().findIndex((i) => i.sid === id)); }, caught.id); await wait(200);
    ok('カタログが調整値と同じになった曲では「調整値で再生中」を出さない', await pc.evaluate((id) => items()[curIndex()].sid === id && !trimmed.has(id) && $('trimOn').hidden, caught.id));
    await close(pc);
    // 「フルライブ映像より」は映像の種類で付ける（開始を調整した単独映像には付けない）
    const pb = await open('#lib=toro');
    const badge = await pb.evaluate((ids) => { switchTo(CATALOG_ID);
      return ids.map((id) => { const i = items().findIndex((x) => x.sid === id); playIndex(i);
        return { id, now: $('nowLive').querySelector('.tag')?.textContent, row: document.querySelectorAll('#list .row')[i]?.querySelector('.tag')?.textContent }; });
    }, [caught.id, all.find((s) => s.kind === 'full' && !s.hidden).id]);
    const [bs, bf] = badge;   // 開始を調整した単独映像、フルライブ映像の曲
    ok('バッジは映像の種類で: 開始を調整した単独映像は「単独映像」、フルライブ映像の曲は「フルライブ映像より」',
      bs.now === '単独映像' && bs.row === '単独映像' && bf.now === 'フルライブ映像より' && bf.row === 'フルライブ映像より', badge);
    await close(pb);
    // スマホ: 横にはみ出さず、動画は上に固定
    const m = await open('tools/trim.html', { width: 390, height: 844, mobile: true });
    await m.waitForFunction(() => $('list').children.length > 0);
    await m.click('#list li'); await wait(300); await m.evaluate(() => scrollTo(0, 600)); await wait(200);
    ok('スマホ: 横スクロールが出ず、動画は画面の上に残る', await m.evaluate(() => document.documentElement.scrollWidth <= innerWidth
      && Math.round(document.querySelector('.stage').getBoundingClientRect().top) === 0));
    await close(m);
  },
};

(async () => {
  const server = spawn('python3', ['-m', 'http.server', String(PORT), '--bind', '127.0.0.1'], { cwd: ROOT, stdio: 'ignore' });
  try {
    for (let i = 0; i < 50; i++) { try { await fetch(BASE + 'index.html'); break; } catch { await wait(100); } }
    browser = await chromium.launch(CHROMIUM ? { executablePath: CHROMIUM } : {});
    const only = process.argv.slice(2);
    for (const [name, fn] of Object.entries(TESTS)) {
      if (only.length && !only.includes(name)) continue;
      console.log(`■ ${name}`);
      try { await fn(); } catch (e) { failed++; console.log(`  NG  ${name} の途中で止まりました: ${e.message.split('\n')[0]}`); }
    }
    if (errors.length) { failed += errors.length; console.log('■ ページのエラー'); errors.forEach((e) => console.log('  NG  ' + e)); }
    console.log(`\n${passed} 件 OK、${failed} 件 NG`);
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
  process.exit(failed ? 1 : 0);
})();
