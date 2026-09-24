#!/usr/bin/env node
/* rec.html の「1 走行ぶんを CSV にして払い出す」を、本物のブラウザで確かめる。
 *
 *     node tools/test_rec_csv.mjs
 *
 * ヘッドレス Chrome で rec.html をローカルサーバから開き、基板が BLE で流す転送行
 * （`BEGIN` / `D` / `END`）を実物の .bin から作って `xferLine` に食わせる。BLE も
 * 基板も要らない。書き出し（`dl`）は横取りして中身を比べる。
 *
 * 確かめること
 *   1. パートがそろうまで CSV を出さない
 *   2. そろったら出し、中身が klcsv.js を直接呼んだ結果と一致する
 *   3. アンカーの無い走行（auto0014）を車速で合わせる
 *   4. 払い出したら直前の 1 走行だけを残し、それより前は消す
 *   5. 基板が先に消したパートがある走行は、手元の分だけで作る
 *   6. 記録中の走行には手を出さない
 */
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const KLCSV = createRequire(import.meta.url)(path.join(ROOT, 'klcsv.js'));
const LOGS = path.join(ROOT, 'private', 'logs');
const PROF = path.join(ROOT, '..', 'work', '.intermediate', 'chrome-rec-test');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const HTTP = 8765, CDP = 9223;
const sleep = ms => new Promise(r => setTimeout(r, ms));

let fail = 0;
const ok = (c, m) => { console.log((c ? '  ✓ ' : '  ✗ ') + m); if (!c) fail++; };

fs.rmSync(PROF, {recursive: true, force: true});
const srv = spawn('python3', ['-m', 'http.server', String(HTTP), '--bind', '127.0.0.1'], {cwd: ROOT, stdio: 'ignore'});
const chr = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${CDP}`, `--user-data-dir=${PROF}`,
                           '--no-first-run', 'about:blank'], {stdio: 'ignore'});
const cleanup = () => { try { chr.kill(); } catch (e) {} try { srv.kill(); } catch (e) {} };
process.on('exit', cleanup);

let ws, seq = 0;
const pend = new Map();
async function cdp(method, params = {}) {
  const id = ++seq;
  ws.send(JSON.stringify({id, method, params}));
  return new Promise((res, rej) => pend.set(id, {res, rej}));
}
async function ev(expr) {
  const r = await cdp('Runtime.evaluate', {expression: expr, awaitPromise: true, returnByValue: true});
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  return r.result.value;
}

try {
  let tabs;
  for (let i = 0; i < 50; i++) {
    try { tabs = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json(); break; } catch (e) { await sleep(200); }
  }
  ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r));
  ws.addEventListener('message', e => {
    const m = JSON.parse(e.data);
    if (m.id && pend.has(m.id)) { pend.get(m.id).res(m.result || {}); pend.delete(m.id); }
  });
  await cdp('Page.enable');
  await cdp('Page.navigate', {url: `http://127.0.0.1:${HTTP}/rec.html`});
  for (let i = 0; i < 50 && !(await ev('typeof maybeCsv === "function" && typeof KLCSV === "object"').catch(() => false)); i++) await sleep(200);

  // 書き出しを横取りする。.bin の保存は止め、CSV は中身を取っておく。ログも拾う
  await ev(`window.__dl = []; window.__say = [];
    dl = (name, text) => __dl.push({name, text});
    dlBin = () => {};
    const _say = say; say = t => { __say.push(t); _say(t); };
    baseDone = true; 'ok'`);

  const gpsOf = f => KLCSV.parseGpsCsv(fs.readFileSync(path.join(LOGS, f), 'utf8'));
  const setGps = async g => ev(`pts = ${JSON.stringify(g.map(p => ({t: Math.round(p.t * 1000), lat: p.lat,
    lon: p.lon, alt: p.alt, spd: p.kmh == null ? null : p.kmh / 3.6, acc: p.acc})))}; 'ok'`);
  const partsOf = pre => fs.readdirSync(LOGS).filter(f => f.startsWith(pre + '_') && f.endsWith('.bin')).sort();
  const u8 = f => new Uint8Array(fs.readFileSync(path.join(LOGS, f)));

  /** 基板の `get` と同じ形で 1 パートを流す */
  async function transfer(name) {
    const b = fs.readFileSync(path.join(LOGS, name));
    const b64 = b.toString('base64'), lines = [`BEGIN /${name} ${b.length}`];
    for (let i = 0; i < b64.length; i += 168) lines.push('D ' + b64.slice(i, i + 168));
    lines.push('END ' + zlib.crc32(b).toString(16).padStart(8, '0'));
    await ev(`(() => { for (const l of ${JSON.stringify(lines)}) xferLine(l); return 1; })()`);
    await sleep(400);                                  // IndexedDB と CSV 組み立ては非同期
  }
  /** 基板の `ls` の一覧を流す（最終行まで） */
  async function ls(names) {
    const lines = names.map(n => `  ${n}   ${fs.statSync(path.join(LOGS, n)).size} バイト`);
    lines.push(`${names.length} ファイル / 0 バイト  空き 11000 KB`);
    await ev(`(() => { seen = {}; lsFresh = false; for (const l of ${JSON.stringify(lines)}) { lsLine(l) || lsEnd(l); } return 1; })()`);
    await sleep(400);
  }
  const csvCount = () => ev('__dl.length');
  const keys = () => ev(`idb('parts','readonly', s => s.getAllKeys())`);

  // ── 1〜2: 夕方（アンカーあり）─────────────────────────────
  console.log('夕方 auto0016（アンカーあり・3 パート）');
  const g16 = gpsOf('gps_2026-09-24T1042.csv');
  await setGps(g16);
  const p16 = partsOf('auto0016');
  await ls(p16);
  await transfer(p16[0]); await transfer(p16[1]);
  ok(await csvCount() === 0, 'パートが 2/3 のうちは CSV を出さない');
  await transfer(p16[2]);
  const d16 = await ev('__dl[0]');
  ok(d16 && d16.name === 'auto0016.csv', `そろったら auto0016.csv を出す`);
  const want16 = KLCSV.build(p16.map(n => ({name: n, u8: u8(n)})), g16).csv;
  ok(d16 && d16.text === want16, `中身が klcsv.js 直呼びと一致（${want16.split('\n').length - 2} 行）`);

  // ── 3〜4: 朝（アンカーなし）─────────────────────────────
  console.log('朝 auto0014（アンカーなし・3 パート）');
  const g14 = gpsOf('gps_2026-09-24T0012.csv');
  await setGps(g14.concat(g16));                        // 1 日ぶんが溜まっている状態
  const p14 = partsOf('auto0014');
  await ls(p14);
  for (const n of p14) await transfer(n);
  const d14 = await ev('__dl[1]');
  ok(d14 && d14.name === 'auto0014.csv', 'auto0014.csv を出す');
  const said = (await ev('__say.join("")'));
  ok(/auto0014\.csv .*車速で合わせた/.test(said), '車速で時刻を合わせた');
  const first = d14 && d14.text.split('\n')[1].split(',')[1];
  ok(first && first.startsWith('2026-09-24T00:12:46'), `先頭行の時刻 ${first}（手計算 00:12:46.4Z）`);
  const k = await keys();
  ok(k.every(n => n.startsWith('auto0014')) && k.length === 3,
     `払い出し後は直前の 1 走行だけ残る（${k.join(' ')}）`);

  // ── 5: 先頭パートが基板から消えている ─────────────────────────
  console.log('auto0002（先頭パートが基板から消えている）');
  await ls(['auto0002_02.bin']);
  await transfer('auto0002_02.bin');
  const d02 = await ev('__dl[2]');
  ok(d02 && d02.name === 'auto0002.csv', '手元の 1 パートだけで auto0002.csv を出す');
  ok(/auto0002\.csv .*1 パート欠け/.test(await ev('__say.join("")')), '欠けを 1 パートと報告する');
  const k2 = await keys();
  ok(!k2.some(n => n.startsWith('auto0014')) && k2.includes('auto0002_02.bin'), '古い走行（auto0014）は消えた');

  // ── 6: 記録中 ────────────────────────────────────────────
  console.log('auto0012（記録中）');
  await ev(`activeLog = 'auto0012_01.bin'; 1`);
  await ls(['auto0012_01.bin']);
  await transfer('auto0012_01.bin');                   // 記録中は本来転送しないが、来ても組み立てない
  ok(await csvCount() === 3, '記録中の走行は CSV にしない');
  await ev(`activeLog = null; 1`);
  await ls(['auto0012_01.bin']);                       // 記録が止まって ls を取り直した
  ok(await csvCount() === 4 && (await ev('__dl[3].name')) === 'auto0012.csv', '記録が止まれば出す');

  // 一覧の `CSV` ボタン（払い出し直し）
  await ev(`renderFiles(); 1`);
  ok(await ev(`!!document.querySelector('[data-csv="auto0012"]')`), '直前の走行に CSV ボタンが出る');
  await ev(`document.querySelector('[data-csv="auto0012"]').click(); 1`);
  await sleep(500);
  ok(await csvCount() === 5, 'ボタンで払い出し直せる');
} catch (e) {
  fail++; console.log('  ✗ 例外: ' + e.message);
} finally {
  cleanup();
}
console.log(fail ? `\n失敗 ${fail} 件` : '\nすべて通った');
process.exit(fail ? 1 : 0);
