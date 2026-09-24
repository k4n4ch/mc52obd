/* 基板のログ（.bin）を、ビュワー（map.html）が読める CSV にする。
 *
 * **rec.html と tools/bin2csv.mjs が同じこのファイルを使う。** 変換の実装を 1 つにして、
 * スマホで出した CSV と Mac で出した CSV が食い違わないようにする。
 *
 * tools/klcsv.py の移植で、列と換算は同一。違いは 1 点だけ —— **時刻の基準
 * （ヘッダの壁時計も `t=` アンカーも）が無いとき、車速バイトと GPS 速度の相互相関で
 * 合わせる。** 自動記録はスマホが繋がらないとアンカーを持たない（auto0014）。
 *
 *   ファイル先頭   "MC52" ver:u8  開始壁時計:u32(unix)
 *   レコード       type:u8  dt:u16(前レコードからの ms)  len:u8  data[len]
 *   type           0x01 独自層の応答 / 0x02 標準層の応答 / 0x03 要求 / 0x10 メモ
 */
(function (root) {
  'use strict';

  const T_PROP = 0x01, T_NOTE = 0x10;
  const COLS = ['t_sec', 'iso_time', '0C_rpm', '0D_speed', '11_tps', '45_tps_rel',
                '05_ect', '0F_iat', '0B_map', '42_volt', '0E_adv', 'skew_ms',
                'drive', 'i8', 'inj'];
  const GPS_COLS = ['lat', 'lon', 'speed_gps', 'gps_acc', 'alt'];
  /** (`[17]`+0.5)/GPS。2026-09-24 の 2 走行で 30〜109km/h 平坦（FINDINGS.md） */
  const SPD_PER_GPS = 0.947;
  const td = new TextDecoder('utf-8');

  const tableOf = p => (p.length >= 4 && p[2] === 0x71) ? p[3] : null;

  /** 1 パートをレコードに分解する。末尾が切れていれば、そこまでを返す。 */
  function parseBin(u8) {
    if (u8.length < 9 || u8[0] !== 0x4D || u8[1] !== 0x43 || u8[2] !== 0x35 || u8[3] !== 0x32)
      throw new Error('先頭が MC52 でない');
    const hdr = (u8[5] | (u8[6] << 8) | (u8[7] << 16) | (u8[8] << 24)) >>> 0;
    const recs = [];
    let i = 9, ms = 0, anchor = null, truncated = false;
    while (i + 4 <= u8.length) {
      const typ = u8[i], dt = u8[i + 1] | (u8[i + 2] << 8), ln = u8[i + 3];
      i += 4;
      if (i + ln > u8.length) { truncated = true; break; }
      const p = u8.subarray(i, i + ln);
      i += ln; ms += dt;
      recs.push({ms, typ, p});
      if (typ === T_NOTE && anchor === null) {
        const m = /^t=(\d{10})$/.exec(td.decode(p).trim());
        if (m) anchor = {ms, epoch: +m[1]};
      }
    }
    return {hdr, recs, anchor, truncated, lastMs: recs.length ? recs[recs.length - 1].ms : 0};
  }

  /** パートを名前順に連結する。**`dt` の連鎖はパートをまたいでも切れていない**ので、
   *  前のパートの最終時刻を足せば隙間なく繋がる。時刻の基準は、先頭パートのヘッダ
   *  （時計が合っていれば）→ 最初に見つかった `t=` アンカーの順で取る（klcsv.py と同じ）。 */
  function mergeParts(parts) {
    const sorted = parts.slice().sort((a, b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
    const out = [];
    let base = null, baseFrom = null, off = 0, truncated = 0;
    sorted.forEach((pt, k) => {
      const b = parseBin(pt.u8);
      if (!b.recs.length) return;
      if (b.truncated) truncated++;
      if (k === 0 && b.hdr >= 1700000000) { base = b.hdr; baseFrom = 'header'; }
      for (const r of b.recs) out.push({ms: off + r.ms, typ: r.typ, p: r.p});
      if (b.anchor && base === null) {
        base = b.anchor.epoch - (off + b.anchor.ms) / 1000; baseFrom = 'anchor';
      }
      off += b.lastMs;
    });
    return {recs: out, base, baseFrom, truncated, nParts: sorted.length};
  }

  /** `0x11` 1 フレームを 1 行にし、直前の `0xD1` の駆動状態を添える。 */
  function toRows(recs) {
    const rows = [];
    let drive = null, i8 = null;
    for (const r of recs) {
      if (r.typ !== T_PROP) continue;
      const t = tableOf(r.p), p = r.p;
      if (t === 0xD1 && p.length >= 11) { drive = p[4]; i8 = p[8]; continue; }
      if (t !== 0x11 || p.length < 25) continue;
      rows.push({
        ms: r.ms,
        rpm: (p[4] << 8) | p[5], spd: p[17],
        tps: p[6] * 100 / 255, tpsRel: p[7] * 100 / 255,
        ect: p[9] - 40, iat: p[11] - 40, map: p[13], volt: p[16] / 10,
        adv: p[20] / 2 - 64,                       // 標準層 0E と同じ符号化
        drive, i8, inj: (p[18] << 8) | p[19],
      });
    }
    return rows;
  }

  /** 測位は {t: epoch 秒, lat, lon, kmh, acc, alt}。時刻順に並べ、同時刻の重複を落とす。 */
  function normGps(gps) {
    const g = (gps || []).filter(x => x && isFinite(x.t) && isFinite(x.lat) && isFinite(x.lon))
      .slice().sort((a, b) => a.t - b.t);
    return g.filter((x, i) => i === 0 || x.t !== g[i - 1].t);
  }

  /** **緯度経度と速度は線形補間する。** 1Hz の測位に対し行は 5Hz なので、最近傍だと
   *  地図が階段になる。精度は最近傍のまま（補間する量ではない）。3 秒を超える欠けは跨がない。 */
  function gpsAt(g, t) {
    let lo = 0, hi = g.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (g[m].t <= t) lo = m + 1; else hi = m; }
    if (lo === 0 || lo >= g.length) return null;
    const a = g[lo - 1], b = g[lo];
    if (b.t - a.t > 3) return null;
    const w = (t - a.t) / (b.t - a.t);
    const lerp = (x, y) => (x == null || y == null) ? null : x + (y - x) * w;
    const near = w < 0.5 ? a : b;
    return {lat: lerp(a.lat, b.lat), lon: lerp(a.lon, b.lon),
            speed_gps: lerp(a.kmh, b.kmh), gps_acc: near.acc, alt: lerp(a.alt, b.alt)};
  }

  /** **時刻の基準が無いとき、車速と GPS 速度の相互相関で合わせる。**
   *  auto0014 で確かめた手順: 最良点の平均誤差 0.50km/h に対し、±10 秒の外の次点は
   *  13.2km/h。止まっている区間はどこにでも一致するので、動いている行だけを使う。
   *  1 秒刻みで全域を探し、最良点の周りを 0.1 秒刻みで詰める。 */
  function alignBySpeed(rows, g) {
    const mov = rows.filter(r => r.spd >= 5);
    if (mov.length < 60 || g.length < 60) return null;
    const step = Math.max(1, Math.floor(mov.length / 400));
    const S = [];
    for (let i = 0; i < mov.length; i += step)
      S.push({t: mov[i].ms / 1000, v: (mov[i].spd + 0.5) / SPD_PER_GPS});
    // GPS 速度を 1 秒格子に敷く（3 秒を超える欠けは NaN）
    const g0 = Math.floor(g[0].t), n = Math.ceil(g[g.length - 1].t) - g0 + 1;
    const G = new Float64Array(n).fill(NaN);
    for (let k = 0, j = 0; k < n; k++) {
      const t = g0 + k;
      while (j + 1 < g.length && g[j + 1].t <= t) j++;
      const a = g[j], b = g[j + 1];
      if (!b || a.t > t || b.t - a.t > 3 || a.kmh == null || b.kmh == null) continue;
      G[k] = a.kmh + (b.kmh - a.kmh) * (t - a.t) / (b.t - a.t);
    }
    const span = S[S.length - 1].t;
    const cost = off => {                          // off = 行の t=0 が g0 から何秒後か
      let s = 0, c = 0;
      for (const x of S) {
        const f = off + x.t, k = Math.floor(f);
        if (k < 0 || k + 1 >= n) continue;
        const a = G[k], b = G[k + 1];
        if (a !== a || b !== b) continue;
        s += Math.abs(x.v - (a + (b - a) * (f - k))); c++;
      }
      return c >= S.length * 0.8 ? s / c : Infinity;
    };
    const coarse = [];
    for (let off = 0; off + span < n; off++) coarse.push([cost(off), off]);
    if (!coarse.length) return null;
    coarse.sort((a, b) => a[0] - b[0]);
    const best = coarse[0];
    if (!isFinite(best[0])) return null;
    const other = coarse.find(c => Math.abs(c[1] - best[1]) > 10);
    let fine = best;
    for (let d = -20; d <= 20; d++) {
      const off = best[1] + d / 10, c = cost(off);
      if (c < fine[0]) fine = [c, off];
    }
    const second = other ? other[0] : Infinity;
    // **一意に決まったときだけ採る。** 平均誤差が小さく、次点と 2 倍以上離れていること
    if (fine[0] > 3 || second < fine[0] * 2) return {ok: false, mae: fine[0], second};
    return {ok: true, base: g0 + fine[1], mae: fine[0], second};
  }

  const r2 = (x, d) => { const k = Math.pow(10, d); return Math.round(x * k) / k; };
  function iso(epochSec) { return new Date(Math.round(epochSec * 1000)).toISOString(); }

  /** parts: [{name, u8}]、gps: 測位（任意）。CSV の文字列と要約を返す。 */
  function build(parts, gps) {
    const m = mergeParts(parts);
    const rows = toRows(m.recs);
    const g = normGps(gps);
    let base = m.base, baseFrom = m.baseFrom, align = null;
    if (base === null && g.length) {
      align = alignBySpeed(rows, g);
      if (align && align.ok) { base = align.base; baseFrom = 'speed'; }
    }
    const withGps = g.length > 0;
    const cols = COLS.concat(withGps ? GPS_COLS : []);
    const out = [cols.join(',')];
    let matched = 0;
    for (const r of rows) {
      const v = [r2(r.ms / 1000, 3), base === null ? '' : iso(base + r.ms / 1000),
                 r.rpm, r.spd, r2(r.tps, 2), r2(r.tpsRel, 2), r.ect, r.iat, r.map,
                 r2(r.volt, 1), r2(r.adv, 1), 0,
                 r.drive === null ? '' : r.drive, r.i8 === null ? '' : r.i8, r.inj];
      if (withGps) {
        const q = base === null ? null : gpsAt(g, base + r.ms / 1000);
        if (q) matched++;
        for (const k of GPS_COLS) v.push(!q || q[k] == null ? '' : r2(q[k], 7));
      }
      out.push(v.join(','));
    }
    const span = m.recs.length ? m.recs[m.recs.length - 1].ms / 1000 : 0;
    return {csv: out.join('\n') + '\n', nRows: rows.length, nParts: m.nParts,
            truncated: m.truncated, base, baseFrom, align, matched, span};
  }

  /** 測位 CSV（rec.html の書き出し形式）を build() が受ける形にする。 */
  function parseGpsCsv(text) {
    const L = text.split(/\r?\n/).filter(l => l.trim());
    if (!L.length) return [];
    const h = L[0].split(','), ix = n => h.indexOf(n);
    const iT = ix('epoch_ms'), iLa = ix('lat'), iLo = ix('lon'), iS = ix('speed_mps'),
          iA = ix('acc_m'), iH = ix('alt_m');
    const num = s => (s === undefined || s === '' || s === 'null') ? null : +s;
    return L.slice(1).map(l => {
      const c = l.split(',');
      const s = num(c[iS]);
      return {t: num(c[iT]) / 1000, lat: num(c[iLa]), lon: num(c[iLo]),
              kmh: s === null ? null : s * 3.6, acc: num(c[iA]), alt: num(c[iH])};
    });
  }

  /** rec.html の測位点 {t: epoch ms, lat, lon, alt, spd(m/s), acc} を変換する。 */
  const fromPts = pts => (pts || []).map(p => ({t: p.t / 1000, lat: p.lat, lon: p.lon,
    kmh: p.spd == null ? null : p.spd * 3.6, acc: p.acc, alt: p.alt}));

  const api = {build, parseBin, mergeParts, toRows, alignBySpeed, parseGpsCsv, fromPts,
               COLS, GPS_COLS};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.KLCSV = api;
})(typeof self !== 'undefined' ? self : this);
