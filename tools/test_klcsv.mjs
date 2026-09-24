#!/usr/bin/env node
/* klcsv.js（rec.html と bin2csv.mjs が使う）が klcsv.py と同じ CSV を出すかを確かめる。
 *
 *     node tools/test_klcsv.mjs
 *
 * 実走ログが要る（private/logs/）。無いケースは飛ばす。
 *
 * **数値で比べる。** 文字列では比べない —— Python は `12.0`、JS は `12` と書くうえ、
 * 丸めも Python は偶数丸め・JS は四捨五入で、最後の桁が 1 違いうる。許容は各列の
 * 表示桁の 1 単位。`iso_time` は Python が切り捨て・JS が四捨五入なので 1ms まで許す。
 */
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const KLCSV = createRequire(import.meta.url)(path.join(ROOT, 'klcsv.js'));
const LOGS = path.join(ROOT, 'private', 'logs');
const TMP = path.join(ROOT, '..', 'work', '.intermediate', 'test_klcsv');
fs.mkdirSync(TMP, {recursive: true});

const TOL = {t_sec: 1e-3, '11_tps': 0.01, '45_tps_rel': 0.01, '42_volt': 0.1, '0E_adv': 0.1,
             lat: 2e-7, lon: 2e-7, speed_gps: 2e-7, gps_acc: 2e-7, alt: 2e-7};
let fail = 0, ran = 0;
const ok = (c, m) => { if (!c) { fail++; console.log('  ✗ ' + m); } };

function parts(prefix) {
  return fs.readdirSync(LOGS).filter(f => f === prefix + '.bin' || (f.startsWith(prefix + '_') && f.endsWith('.bin')))
    .sort().map(f => path.join(LOGS, f));
}
// Python の csv は行末が \r\n、klcsv.js は \n
const table = t => { const L = t.trim().split(/\r?\n/); return {h: L[0].split(','), r: L.slice(1).map(l => l.split(','))}; };

function compare(name, prefix, gpsFile) {
  const bins = parts(prefix);
  const gp = gpsFile && path.join(LOGS, gpsFile);
  if (!bins.length || (gp && !fs.existsSync(gp))) { console.log(`- ${name}: ログが無いので飛ばす`); return; }
  ran++;
  const pyOut = path.join(TMP, prefix + '.py.csv');
  execFileSync('python3', [path.join(ROOT, 'tools', 'klcsv.py'), ...bins, '-o', pyOut,
                           ...(gp ? ['--gps', gp] : [])], {stdio: 'pipe'});
  const gps = gp ? KLCSV.parseGpsCsv(fs.readFileSync(gp, 'utf8')) : null;
  const js = KLCSV.build(bins.map(f => ({name: path.basename(f), u8: new Uint8Array(fs.readFileSync(f))})), gps);
  const P = table(fs.readFileSync(pyOut, 'utf8')), J = table(js.csv);
  console.log(`- ${name}: ${J.r.length} 行（基準 ${js.baseFrom}）`);
  ok(P.h.join() === J.h.join(), `列が違う\n    py ${P.h}\n    js ${J.h}`);
  ok(P.r.length === J.r.length, `行数 py ${P.r.length} / js ${J.r.length}`);
  let bad = 0;
  for (let i = 0; i < Math.min(P.r.length, J.r.length) && bad < 5; i++) {
    for (let k = 0; k < P.h.length; k++) {
      const c = P.h[k], a = P.r[i][k], b = J.r[i][k];
      let same;
      if (a === '' || b === '') same = a === b;
      else if (c === 'iso_time') same = Math.abs(Date.parse(a) - Date.parse(b)) <= 1;
      else same = Math.abs(+a - +b) <= (TOL[c] || 0) + 1e-9;
      if (!same) { bad++; ok(false, `行 ${i + 1} ${c}: py ${a} / js ${b}`); break; }
    }
  }
}

compare('夕方（アンカーあり・測位あり）', 'auto0016', 'gps_2026-09-24T1042.csv');
compare('09-19 1 本目（ヘッダ時刻・測位あり）', 'r260919_1150', 'gps_2026-09-19T0250.csv');
compare('09-19 2 本目（ヘッダ時刻・測位あり）', 'r260919_1224', 'gps_2026-09-19T0324.csv');
compare('09-19 自動記録（アンカーあり・測位なし）', 'auto0002', null);

// アンカーの無い走行を車速で合わせる。手で求めた基準は t=0 が 00:12:46.4Z
{
  const bins = parts('auto0014'), gp = path.join(LOGS, 'gps_2026-09-24T0012.csv');
  if (bins.length && fs.existsSync(gp)) {
    ran++;
    const js = KLCSV.build(bins.map(f => ({name: path.basename(f), u8: new Uint8Array(fs.readFileSync(f))})),
                           KLCSV.parseGpsCsv(fs.readFileSync(gp, 'utf8')));
    const want = Date.parse('2026-09-24T00:12:46.4Z') / 1000;
    console.log(`- 朝（アンカーなし）: 基準 ${js.baseFrom}、手計算との差 ${(js.base - want).toFixed(2)} 秒`
      + `、誤差 ${js.align.mae.toFixed(2)} / 次点 ${js.align.second.toFixed(1)}km/h`);
    ok(js.baseFrom === 'speed', '車速で合っていない');
    ok(Math.abs(js.base - want) <= 0.5, '手計算と 0.5 秒以上ずれる');
    // 測位の無い区間しか渡さなければ、合わせずに諦めること（誤って合わせない）
    const far = KLCSV.parseGpsCsv(fs.readFileSync(path.join(LOGS, 'gps_2026-09-24T1042.csv'), 'utf8'));
    const js2 = KLCSV.build(bins.map(f => ({name: path.basename(f), u8: new Uint8Array(fs.readFileSync(f))})), far);
    console.log(`- 朝のログに夕方の測位だけを渡す: 基準 ${js2.baseFrom ?? 'なし'}`);
    ok(js2.base === null, '別の走行の測位に誤って合わせた');
  }
}

console.log(fail ? `\n失敗 ${fail} 件` : `\n${ran} ケースすべて一致`);
process.exit(fail ? 1 : 0);
