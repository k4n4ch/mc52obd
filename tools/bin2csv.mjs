#!/usr/bin/env node
/* 基板のログを、セッション単位でビュワー用 CSV にする（一括）。
 *
 * 変換の本体はリポジトリ直下の `klcsv.js`。**rec.html がスマホで使うのと同じ実装**なので、
 * ここで出した CSV とスマホで出した CSV は同じになる。
 *
 *     node tools/bin2csv.mjs                       # private/logs/*.bin を全部 → private/csv/
 *     node tools/bin2csv.mjs private/logs/auto0014_*.bin --out /tmp/x
 *
 * **パートは `名前_NN.bin` を 1 セッションに束ねる。** 測位は private/logs/gps_*.csv を
 * 全部読んで重ねて渡す。時刻の基準（ヘッダ・`t=` アンカー）が無いセッションは、
 * klcsv.js が車速と GPS 速度の相互相関で合わせる。`0x11` が 30 行（6 秒）
 * に満たないセッション（停車の探索、`0x11` を読んでいない走行）は出さない。
 */
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const KLCSV = createRequire(import.meta.url)(path.join(ROOT, 'klcsv.js'));

const args = process.argv.slice(2);
let out = path.join(ROOT, 'private', 'csv');
const files = [];
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--out') out = args[++i];
  else files.push(args[i]);
}
const logs = path.join(ROOT, 'private', 'logs');
if (!files.length)
  for (const f of fs.readdirSync(logs).sort()) if (f.endsWith('.bin')) files.push(path.join(logs, f));

const sess = new Map();
for (const f of files) {
  const n = path.basename(f), m = /^(.*)_(\d{2})\.bin$/.exec(n);
  const b = m ? m[1] : n.replace(/\.bin$/, '');
  if (!sess.has(b)) sess.set(b, []);
  sess.get(b).push({name: n, u8: new Uint8Array(fs.readFileSync(f))});
}

const gps = [];
for (const f of fs.readdirSync(logs).sort())
  if (/^gps_.*\.csv$/.test(f)) gps.push(...KLCSV.parseGpsCsv(fs.readFileSync(path.join(logs, f), 'utf8')));
console.log(`測位 ${gps.length} 点（重複を含む）/ セッション ${sess.size} 本`);

fs.mkdirSync(out, {recursive: true});
for (const [b, parts] of sess) {
  let r;
  try { r = KLCSV.build(parts, gps); }
  catch (e) { console.log(`  ${b.padEnd(14)} 読めない: ${e.message}`); continue; }
  // **30 行（6 秒）未満は出さない。** `0x11` を読んでいない走行でも起動時の snap が 1 行残る
  if (r.nRows < 30) { console.log(`  ${b.padEnd(14)} 0x11 が ${r.nRows} 行しか無いので出さない`); continue; }
  fs.writeFileSync(path.join(out, b + '.csv'), r.csv);
  const t = r.base === null ? '時刻なし'
    : `${new Date(r.base * 1000).toISOString().slice(0, 19)}Z（${r.baseFrom}`
      + (r.align && r.align.ok ? ` 誤差 ${r.align.mae.toFixed(2)} / 次点 ${r.align.second.toFixed(1)}km/h` : '') + '）';
  const why = r.base === null && r.align ? `  ※ 合わせられない（誤差 ${r.align.mae.toFixed(2)} / 次点 ${r.align.second.toFixed(1)}）` : '';
  console.log(`  ${b.padEnd(14)} ${String(r.nRows).padStart(5)} 行 ${(r.span / 60).toFixed(1).padStart(5)} 分 `
    + `${r.nParts} パート  ${t}  測位 ${r.matched}/${r.nRows}${r.truncated ? '  末尾切れ' : ''}${why}`);
}
console.log(`→ ${out}`);
