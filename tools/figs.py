#!/usr/bin/env python3
"""独自層（Track B）の実測から図を作る。gearing.py と同じく SVG を直接書く。

    python3 tools/figs.py --logs private/logs --out docs

入力は基板のログ（`*.bin`）で、`klcsv.py` と同じ経路で値に直す。位置情報は
使わないので、出力した SVG から経路は復元できない。

**判定は `map.html` の ELM327 経路と同じ式**（k 固定・段ごとの窓・量子化項）。
`docs/gear.md`「真値と突き合わせた」節の数値を再現する側に揃えてあり、
変速レート制限は掛けていない（あの節の集計に入っていないため）。
"""
import argparse, collections, csv, glob, math, os, re, statistics as st, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kldecode import records, table_of                 # noqa: E402
from klcsv import merge_parts, load_gps, gps_at        # noqa: E402

# ── 同定（諸元・ファーム定数）─────────────────────────────
GEAR = {1: 3.416, 2: 2.250, 3: 1.650, 4: 1.350, 5: 1.166, 6: 1.038}
PRIMARY, SECONDARY = 2.807, 2.571
CIRC = math.pi * (17 * 25.4 + 2 * 150 * 0.60) / 1000
R = {n: PRIMARY * GEAR[n] * SECONDARY / (CIRC * 60 / 1000) for n in GEAR}
GEARS = [1, 2, 3, 4, 5, 6]
K = 1.0057          # 閉じた定数。較正しない（gear.md）
RPM_MIN = 1700      # アイドル張り付きを切る下限
TOL = 4.0           # 判定窓の設定値（5-6速での窓）

# **公開する図に載せる車速の上限。** 高速道路の最高法定速度を超える点は出さない。
# 実測はいまのところ最大 66km/h なので効いていないが、規則としてここに置く。
SPD_MAX_PUB = 120.0

TOL_PAIR = {n: (R[n] / R[n + 1] - 1) / (R[n] / R[n + 1] + 1) * 100 for n in GEARS[:-1]}
TOL_MAX = min(TOL_PAIR.values())


def gear_win(n, d, tol=TOL):
    """段ごと・向きごとの窓 [%]。外側（1速の上・6速の下）は設定値そのまま。"""
    f = tol / TOL_MAX
    if d > 0:
        return f * TOL_PAIR[n - 1] if n > GEARS[0] else tol
    return f * TOL_PAIR[n] if n < GEARS[-1] else tol


# ── 描画の共通部（gearing.py と同じ意匠）────────────────────
C_AX, C_TX, C_GR = '#9aa4ae', '#767f89', '#808a94'
GC = {1: '#2a78d6', 2: '#eb6834', 3: '#1baf7a',
      4: '#eda100', 5: '#e87ba4', 6: '#008300'}
C_OK, C_NG = '#1c1c1c', '#c2410c'
FONT = "-apple-system,'Helvetica Neue',Arial,'Hiragino Sans',Meiryo,sans-serif"


def _hdr(w, h, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'width="{w}" height="{h}" font-family="{FONT}" role="img">'
            f'<title>{title}</title>'
            # **地を必ず塗る。** GitHub のダークテーマは透明 SVG の背後を黒にするので、
            # 塗らないと黒・濃灰の文字と点が消える。PDF や外部への貼り付けでも同じ。
            f'<rect x="0" y="0" width="{w}" height="{h}" fill="#ffffff"/>')


def _txt(x, y, s, size=12, fill=None, anchor='start', weight='normal', op=None):
    o = f' opacity="{op}"' if op else ''
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill or C_TX}" '
            f'text-anchor="{anchor}" font-weight="{weight}"{o}>{s}</text>')


def _line(x1, y1, x2, y2, col, w=1.0, dash=None, op=None):
    da = f' stroke-dasharray="{dash}"' if dash else ''
    oa = f' stroke-opacity="{op}"' if op else ''
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{col}" stroke-width="{w}"{da}{oa}/>')


def _path(pts, col, w=2.0, dash=None):
    d = 'M' + ' L'.join(f'{x:.1f},{y:.1f}' for x, y in pts)
    da = f' stroke-dasharray="{dash}"' if dash else ''
    return (f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{w}" '
            f'stroke-linejoin="round" stroke-linecap="round"{da}/>')


def _dot(x, y, r, col, op=0.55):
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{col}" opacity="{op}"/>'


def _save(path, parts):
    """**viewBox からのはみ出しを弾いてから書く。** 一度 16×16 の格子を
    枠の外へ描いて気づかなかったので、機械で見るようにした。"""
    parts.append('</svg>')
    svg = '\n'.join(parts)
    w, h = (float(v) for v in re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg).groups())
    xs = [float(m) for m in re.findall(r'(?:\bx|x1|x2|cx)="([-\d.]+)"', svg)]
    ys = [float(m) for m in re.findall(r'(?:\by|y1|y2|cy)="([-\d.]+)"', svg)]
    for d in re.findall(r' d="([^"]+)"', svg):
        for a, b in re.findall(r'([-\d.]+),([-\d.]+)', d):
            xs.append(float(a)); ys.append(float(b))
    for r_ in re.finditer(r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" '
                          r'height="([\d.]+)"', svg):
        x, y, rw, rh = (float(v) for v in r_.groups())
        xs.append(x + rw); ys.append(y + rh)
    if max(xs) > w or max(ys) > h or min(xs) < 0 or min(ys) < 0:
        raise SystemExit(f'{path}: viewBox {w:.0f}x{h:.0f} からはみ出している '
                         f'(x {min(xs):.0f}..{max(xs):.0f} / y {min(ys):.0f}..{max(ys):.0f})')
    open(path, 'w', encoding='utf-8').write(svg)
    print(path)


# ── データ ────────────────────────────────────────────────
def load_run(paths, with_base=False):
    """基板のログ 1 走行を行にする。**`0x11` の 1 フレーム = 1 行**、最も近い
    `0xD1` の駆動状態を添える —— `klcsv.py` と同じ組み立て。位置情報は読まない。"""
    recs, base = merge_parts(sorted(paths))
    rows, drive, i8 = [], None, None
    for ms, typ, p in recs:
        if typ != 0x01:
            continue
        t = table_of(p)
        if t == 0xD1 and len(p) >= 11:
            drive, i8 = p[4], p[8]
            continue
        if t != 0x11 or len(p) < 25:
            continue
        rows.append(dict(t=ms / 1000,
                         rpm=float((p[4] << 8) | p[5]), spd=float(p[17]),
                         tps=p[6] * 100 / 255, inj=float((p[18] << 8) | p[19]),
                         drive=drive, i8=i8))
    return (rows, base) if with_base else rows


def pub(rows):
    """公開できる点だけに絞る。車速の上限を超える行を落とす。"""
    return [r for r in rows if r['spd'] is None or r['spd'] <= SPD_MAX_PUB]


def scan_tables(path):
    """テーブル総当たりの結果。要求 `72 05 71 TT CS` と直後の応答を対にする。"""
    res = {}
    pend = None
    for _, _, _, typ, p in records(path):
        if typ == 0x03 and len(p) >= 4 and p[0] == 0x72 and p[2] == 0x71:
            pend = p[3]
        elif typ == 0x01 and pend is not None:
            res[pend] = max(res.get(pend, 0), len(p))
            pend = None
    return res


def judge(rows):
    """ELM327 経路の判定を当て、比・最近傍段・ずれも残す。"""
    for r in rows:
        r['ratio'] = r['best'] = r['dev'] = r['gear'] = None
        sp = None if r['spd'] is None else (0.0 if r['spd'] == 0 else r['spd'] + 0.5)
        if r['rpm'] and r['rpm'] > 500 and sp and sp >= 8.5:
            r['ratio'] = r['rpm'] / sp
        if r['ratio'] is None:
            continue
        b = min(GEARS, key=lambda n: abs(r['ratio'] / (K * R[n]) - 1))
        r['best'], r['dev'] = b, r['ratio'] / (K * R[b]) - 1
        if r['rpm'] < RPM_MIN:
            continue
        win = gear_win(b, r['dev']) / 100 + 0.5 / max(r['spd'] + 0.5, 1)
        if abs(r['dev']) <= win:
            r['gear'] = b
    return rows


# ── fig6 駆動状態で分けた比の散布 ──────────────────────────
def fig_drive(path, rows):
    """比 rpm/(km/h) は段ごとに定数。駆動中は 6 本に張り付き、非伝達は散る。"""
    W, H = 790, 430
    T, B, GAPX = 30, 56, 30
    PW = (W - 46 - 14 - GAPX) / 2
    x0, x1, y0, y1 = 0, 65, 50, 250
    s = [_hdr(W, H, '駆動状態で分けた比の散布')]

    panels = ((0, '`00` 駆動が繋がっている', C_OK),
              (1, '`01` N またはクラッチ切り', C_NG))
    for i, (dv, lab, col) in enumerate(panels):
        L = 46 + i * (PW + GAPX)
        fx = lambda v, L=L: L + (v - x0) / (x1 - x0) * PW
        fy = lambda v: H - B - (v - y0) / (y1 - y0) * (H - T - B)
        s.append(f'<rect x="{L}" y="{T}" width="{PW:.1f}" height="{H-T-B}" '
                 f'fill="none" stroke="{C_AX}" stroke-width="1" opacity="0.4"/>')
        for v in range(0, x1 + 1, 20):
            s.append(_line(fx(v), T, fx(v), H - B, C_GR, 1, op=0.18))
            s.append(_txt(fx(v), H - B + 17, f'{v}', 11.5, anchor='middle'))
        # 段の理論比（水平線）
        for n in GEARS:
            y = fy(K * R[n])
            s.append(_line(L, y, L + PW, y, GC[n], 1.6, op=0.85))
            if i == 0:
                s.append(_txt(L + 5, y - 4, f'{n}速', 11, GC[n], weight='600'))
        sub = [r for r in rows if r['drive'] == dv and r['ratio']]
        out = 0
        for r in sub:
            if not (y0 <= r['ratio'] <= y1) or not (x0 <= r['spd'] <= x1):
                out += 1
                continue
            s.append(_dot(fx(r['spd']), fy(r['ratio']), 2.1, col, 0.42))
        s.append(_txt(L + PW / 2, T - 11, lab.replace('`', ''), 13, col,
                      anchor='middle', weight='600'))
        s.append(_txt(L + PW - 6, T + 16, f'n = {len(sub)}', 11.5, anchor='end'))
        if out:
            s.append(_txt(L + PW - 6, T + 31, f'枠外 {out}', 10.5, anchor='end'))
        if i == 0:
            s.append(_txt(L + 8, H - B - 28, '発進の半クラはエンジンを速くするので', 10.5))
            s.append(_txt(L + 8, H - B - 14, '1速の線より上へ外れる', 10.5))
        s.append(_txt(L + PW / 2, H - 14, '車速（ECU 生値）[km/h]', 12, anchor='middle'))

    s.append(f'<text x="15" y="{(T+H-B)/2:.0f}" font-size="12.5" fill="{C_TX}" '
             f'text-anchor="middle" transform="rotate(-90 15 {(T+H-B)/2:.0f})">'
             f'比　回転数 ÷ 車速 [rpm/(km/h)]</text>')
    for v in range(50, y1 + 1, 50):
        y = H - B - (v - y0) / (y1 - y0) * (H - T - B)
        s.append(_txt(40, y + 4, f'{v}', 11.5, anchor='end'))
    _save(path, s)


# ── fig7 比が原理的に解けない帯 ────────────────────────────
def fig_band(path, rows, band=(20, 40, 1700, 2400)):
    """同じ車速・同じ回転数で、駆動状態だけが答えの質を分ける。"""
    v0, v1, r0, r1 = band
    W, H = 720, 460
    L, Rm, T, B = 62, 176, 28, 54
    fx = lambda v: L + (v - (v0 - 2)) / ((v1 + 2) - (v0 - 2)) * (W - L - Rm)
    fy = lambda v: H - B - (v - (r0 - 100)) / ((r1 + 100) - (r0 - 100)) * (H - T - B)
    s = [_hdr(W, H, '比が原理的に解けない帯')]

    for v in range(v0, v1 + 1, 5):
        s.append(_line(fx(v), T, fx(v), H - B, C_GR, 1, op=0.18))
        s.append(_txt(fx(v), H - B + 17, f'{v}', 11.5, anchor='middle'))
    for p in range(r0 - 100, r1 + 101, 200):
        s.append(_line(L, fy(p), W - Rm, fy(p), C_GR, 1, op=0.18))
        s.append(_txt(L - 8, fy(p) + 4, f'{p}', 11.5, anchor='end'))
    s.append(_txt((L + W - Rm) / 2, H - 14, '車速（ECU 生値）[km/h]', 12.5, anchor='middle'))
    s.append(f'<text x="16" y="{(T+H-B)/2:.0f}" font-size="12.5" fill="{C_TX}" '
             f'text-anchor="middle" transform="rotate(-90 16 {(T+H-B)/2:.0f})">回転数 [rpm]</text>')

    # 各段の線（rpm = k·R·車速）。帯を通るものだけ描く
    for n in GEARS:
        pts = [(fx(v), fy(K * R[n] * v)) for v in range(v0 - 2, v1 + 3)
               if r0 - 100 <= K * R[n] * v <= r1 + 100]
        if len(pts) < 2:
            continue
        s.append(_path(pts, GC[n], 1.8))
        ex, ey = pts[-1]
        inside = ex < fx(v1 + 1.2)
        s.append(_txt(ex + (6 if inside else -4), ey + (4 if inside else -7),
                      f'{n}速', 11.5, GC[n], anchor='start' if inside else 'end',
                      weight='600'))

    inb = lambda r: (r['spd'] and r['rpm'] and v0 <= r['spd'] <= v1
                     and r0 <= r['rpm'] <= r1 and r['ratio'])
    tally = {}
    for dv, col in ((0, C_OK), (1, C_NG)):
        sub = [r for r in rows if r['drive'] == dv and inb(r)]
        tally[dv] = collections.Counter(r['gear'] for r in sub)
        for r in sub:
            x, y = fx(r['spd']), fy(r['rpm'])
            if dv == 0:
                s.append(_dot(x, y, 3.4, col, 0.6))
            else:
                s.append(_line(x - 3.4, y - 3.4, x + 3.4, y + 3.4, col, 1.6))
                s.append(_line(x - 3.4, y + 3.4, x + 3.4, y - 3.4, col, 1.6))

    # 右の内訳
    tx = W - Rm + 14
    s.append(_txt(tx, T + 14, '比推定が答えた段', 12, weight='600'))
    y = T + 40
    for dv, mark, col in ((0, '●', C_OK), (1, '✕', C_NG)):
        n_all = sum(tally[dv].values())
        s.append(_txt(tx, y, f'{mark} index 4 = {dv:02d}', 12, col, weight='600'))
        s.append(_txt(tx, y + 16, '駆動' if dv == 0 else '非伝達', 11, col))
        s.append(_txt(tx + 92, y + 16, f'n = {n_all}', 11, anchor='end'))
        y += 34
        for g in GEARS + [None]:
            c = tally[dv].get(g, 0)
            if not c:
                continue
            s.append(_txt(tx + 8, y, '不確定' if g is None else f'{g}速', 11.5,
                          C_TX if g is None else GC[g]))
            s.append(_txt(tx + 92, y, f'{c}', 11.5, anchor='end', weight='600'))
            y += 16
        y += 12
    s.append(_txt(tx, y + 4, '● は線に乗る', 11))
    s.append(_txt(tx, y + 19, '✕ は線の間に散る', 11))
    s.append(_txt(tx, y + 41, '同じ帯・同じ点で', 11, weight='600'))
    s.append(_txt(tx, y + 56, '答えの質が反転する', 11, weight='600'))
    _save(path, s)


# ── fig8 量子化の余裕が低速で効きすぎている ────────────────
def fig_tol(path, rows):
    """許容の内訳と、その下をくぐる誤答。窓の調整では直せないことを示す。

    **1速と判定した誤答だけを描く。** 窓は段ごと・向きごとに違うので、1 本の
    曲線に全段を重ねると許容の上に点が乗って読めなくなる。1速の上側は隣の段が
    無く窓が設定値 4.0% 固定で、量子化の余裕がそこへ素で足し込まれる ——
    機構がいちばん素直に出る組み合わせ。"""
    W, H = 760, 450
    L, Rm, T, B = 60, 172, 28, 54
    x0, x1, y1 = 8, 60, 12.0
    fx = lambda v: L + (v - x0) / (x1 - x0) * (W - L - Rm)
    fy = lambda v: H - B - v / y1 * (H - T - B)
    s = [_hdr(W, H, '許容の内訳と誤答')]

    for v in range(10, x1 + 1, 10):
        s.append(_line(fx(v), T, fx(v), H - B, C_GR, 1, op=0.18))
        s.append(_txt(fx(v), H - B + 17, f'{v}', 11.5, anchor='middle'))
    for p in range(0, int(y1) + 1, 2):
        s.append(_line(L, fy(p), W - Rm, fy(p), C_GR, 1, op=0.18))
        s.append(_txt(L - 8, fy(p) + 4, f'{p}', 11.5, anchor='end'))
    s.append(_txt((L + W - Rm) / 2, H - 14, '車速（ECU 生値）[km/h]', 12.5, anchor='middle'))
    s.append(f'<text x="15" y="{(T+H-B)/2:.0f}" font-size="12.5" fill="{C_TX}" '
             f'text-anchor="middle" transform="rotate(-90 15 {(T+H-B)/2:.0f})">'
             f'比のずれ・許容 [%]</text>')

    q = lambda v: 100 * 0.5 / (v + 0.5)
    vs = [x0 + i * 0.25 for i in range(int((x1 - x0) / 0.25) + 1)]

    # 通る領域を塗る。**誤答も正答も同じ領域に入る**ことが要点
    poly = [(fx(v), fy(min(TOL + q(v), y1))) for v in vs]
    d = ('M' + ' L'.join(f'{x:.1f},{y:.1f}' for x, y in poly)
         + f' L{fx(x1):.1f},{fy(0):.1f} L{fx(x0):.1f},{fy(0):.1f} Z')
    s_ = f'<path d="{d}" fill="#808a94" opacity="0.10"/>'
    s.append(s_)
    s.append(_path(poly, '#1c1c1c', 2.4))
    s.append(_path([(fx(v), fy(q(v))) for v in vs], C_AX, 1.8, dash='6 4'))
    s.append(_line(fx(x0), fy(TOL), fx(x1), fy(TOL), C_AX, 1.8, dash='2 4'))

    sel = lambda dv: [r for r in rows if r['gear'] == 1 and r['dev'] and r['dev'] > 0
                      and ((r['drive'] == 0) if dv == 0 else (r['drive'] != 0))]
    ok, bad = sel(0), sel(1)
    for r in ok:
        s.append(_dot(fx(r['spd']), fy(100 * r['dev']), 2.6, '#5b6670', 0.32))
    for r in bad:
        s.append(_dot(fx(r['spd']), fy(100 * r['dev']), 3.0, C_NG, 0.85))

    s.append(_txt(fx(33), fy(TOL + q(33)) - 9, '合計＝許容', 12, '#1c1c1c', weight='600'))
    s.append(_txt(fx(33), fy(TOL + q(33)) + 16, 'この下は通る', 11, C_TX))
    s.append(_txt(fx(46), fy(TOL) + 16, '窓（1速の上側）4.0% 固定', 11, C_AX))
    s.append(_txt(fx(40), fy(q(40)) - 9, '量子化の余裕 0.5 / 車速', 11, C_AX))
    s.append(_line(fx(8), fy(0), fx(8), fy(TOL + q(8)), C_NG, 1, dash='3 3'))
    s.append(_txt(fx(8) + 6, fy(TOL + q(8)) - 6, f'8km/h で {TOL + q(8):.1f}%', 11,
                  C_NG, weight='600'))

    tx = W - Rm + 14
    s.append(_txt(tx, T + 14, '1速と答えた点（上側）', 12.5, weight='600'))
    s.append(_txt(tx, T + 34, '● 駆動が繋がっている', 11.5, '#5b6670'))
    s.append(_txt(tx + 140, T + 34, f'{len(ok)}', 11.5, '#5b6670', anchor='end',
                  weight='600'))
    s.append(_txt(tx, T + 52, '● 非伝達＝誤答', 11.5, C_NG))
    s.append(_txt(tx + 140, T + 52, f'{len(bad)}', 11.5, C_NG, anchor='end',
                  weight='600'))
    y = T + 84
    s.append(_txt(tx, y, '車速', 11.5)); s.append(_txt(tx + 140, y, '許容', 11.5, anchor='end'))
    y += 18
    for v in (8, 20, 40):
        s.append(_txt(tx, y, f'{v} km/h', 11.5))
        s.append(_txt(tx + 140, y, f'{TOL + q(v):.1f}%', 11.5, anchor='end', weight='600'))
        y += 17
    y += 16
    for ln, w in (('量子化の項は原理', 'normal'), ('的に正しい。正しい', 'normal'),
                  ('項が、正しい理由', 'normal'), ('で、低速域を通し', '600'),
                  ('すぎている。', '600')):
        s.append(_txt(tx, y, ln, 11, weight=w)); y += 15
    y += 10
    for ln in ('狭めれば本物の低速', '段を弾く —— 灰と赤', 'は同じ領域にいる。'):
        s.append(_txt(tx, y, ln, 11)); y += 15
    _save(path, s)


# ── fig9 駆動状態ゲートの効果 ──────────────────────────────
def fig_gate(path, runs):
    W, H = 820, 340
    s = [_hdr(W, H, '駆動状態ゲートの効果')]
    L, BW = 200, 330
    s.append(_txt(L, 30, '駆動中に段が付いた割合', 13, weight='600'))
    s.append(_txt(L + BW + 70, 30, '非伝達なのに答えた', 13, anchor='end', weight='600'))
    y = 58
    for name, rows in runs:
        d0 = [r for r in rows if r['drive'] == 0]
        elm = sum(1 for r in d0 if r['gear'])
        gate = sum(1 for r in d0 if r['ratio'])
        bad = sum(1 for r in rows if r['gear'] and r['drive'] != 0)
        s.append(_txt(L - 14, y + 26, name, 12, anchor='end', weight='600'))
        s.append(_txt(L - 14, y + 42, f'n = {len(rows)}', 10.5, anchor='end'))
        for i, (val, tot, col, lab) in enumerate(
                ((elm, len(d0), C_AX, 'ELM327 経路'),
                 (gate, len(d0), '#1baf7a', '駆動状態ゲート'))):
            yy = y + i * 22
            w = BW * val / tot
            s.append(f'<rect x="{L}" y="{yy}" width="{BW}" height="16" fill="{C_GR}" '
                     f'opacity="0.13" rx="2"/>')
            s.append(f'<rect x="{L}" y="{yy}" width="{w:.1f}" height="16" fill="{col}" rx="2"/>')
            inb = w > 120
            s.append(_txt(L + w + (-7 if inb else 7), yy + 12.5, f'{100*val/tot:.1f}%',
                          11.5, '#ffffff' if inb else col,
                          anchor='end' if inb else 'start', weight='600'))
            s.append(_txt(L + 7, yy + 12.5, lab, 10.5, '#ffffff'))
        # 誤答
        s.append(_txt(L + BW + 66, y + 13, f'{bad}', 15, C_NG, anchor='end', weight='700'))
        s.append(_txt(L + BW + 70, y + 13, '件', 11, C_NG))
        s.append(_txt(L + BW + 66, y + 35, '0', 15, '#1baf7a', anchor='end', weight='700'))
        s.append(_txt(L + BW + 70, y + 35, '件', 11, '#1baf7a'))
        y += 74
    s.append(_txt(L, y + 2, '棄却していた変速過渡は、駆動中と分かっていれば最近傍で決まる。', 11.5))
    s.append(_txt(L, y + 19, '誤答を弾く役は index 4 が担うので、窓は「どの段か」だけを決めればよい。', 11.5))
    _save(path, s)



# ── figA テーブル総当たりの結果 ────────────────────────────
def fig_scan(path, res):
    """`0x00`〜`0xFF` の 256 本を叩いた結果。実在するのは 7 本だけ。"""
    W, H = 660, 700
    L, T, CELL = 56, 78, 34
    s = [_hdr(W, H, 'テーブル総当たりの結果')]
    live = {t: n for t, n in res.items() if n > 5}
    s.append(_txt(L, 28, '独自層のテーブルを 256 本すべて叩く', 14, '#1c1c1c', weight='600'))
    s.append(_txt(L, 48, f'実在 {len(live)} 本。残り {len(res) - len(live)} 本は長さ 5 の空応答', 12))

    for c in range(16):
        s.append(_txt(L + c * CELL + CELL / 2, T - 8, f'{c:X}', 11, anchor='middle'))
    for r in range(16):
        s.append(_txt(L - 9, T + r * CELL + CELL / 2 + 4, f'{r:X}0', 11, anchor='end'))
    for t in range(256):
        r, c = t >> 4, t & 15
        x, y = L + c * CELL, T + r * CELL
        n = res.get(t, 0)
        on = n > 5
        s.append(f'<rect x="{x}" y="{y}" width="{CELL-3}" height="{CELL-3}" rx="3" '
                 f'fill="{"#1baf7a" if on else "#808a94"}" opacity="{0.9 if on else 0.13}"/>')
        if on:
            s.append(_txt(x + (CELL - 3) / 2, y + 14, f'{t:02X}', 11, '#ffffff',
                          anchor='middle', weight='700'))
            s.append(_txt(x + (CELL - 3) / 2, y + 26, f'{n}B', 9.5, '#ffffff',
                          anchor='middle'))
    y = T + 16 * CELL + 24
    s.append(_txt(L, y, '緑＝応答したテーブル（数字は応答の長さ）', 11.5))
    s.append(_txt(L, y + 17, 'CBR600RR にある 0x10 は無い。0x61 は長さ 25 だが中身が凍結している',
                  11.5))
    _save(path, s)


# ── figC 噴射時間 ──────────────────────────────────────────
def fig_inj(path, blip, cut):
    """標準 OBD 層に無い量。スロットルに追従し、減速では 0 に落ちる。"""
    W, H = 790, 400
    T, B, GAPX = 56, 56, 58
    PW = (W - 56 - 56 - GAPX) / 2
    inj1, rpm1 = 1700, 6000
    s = [_hdr(W, H, '噴射時間の時系列')]

    for i, (seg, ttl, note) in enumerate(
            ((blip, '停車・空吹かし', '開けた瞬間に跳ね、閉じた瞬間に落ちる'),
             (cut, '走行・減速', '燃料カット。噴射が 0 になる'))):
        L = 56 + i * (PW + GAPX)
        t0 = seg[0]['t']
        span = seg[-1]['t'] - t0
        fx = lambda v, L=L, t0=t0, sp=span: L + (v - t0) / sp * PW
        fyi = lambda v: H - B - v / inj1 * (H - T - B)
        fyr = lambda v: H - B - v / rpm1 * (H - T - B)
        s.append(f'<rect x="{L}" y="{T}" width="{PW:.1f}" height="{H-T-B}" fill="none" '
                 f'stroke="{C_AX}" stroke-width="1" opacity="0.4"/>')
        for k in range(0, int(span) + 1, 10 if span > 20 else 2):
            s.append(_line(fx(t0 + k), T, fx(t0 + k), H - B, C_GR, 1, op=0.16))
            s.append(_txt(fx(t0 + k), H - B + 17, f'{k}', 11, anchor='middle'))
        s.append(_path([(fx(r['t']), fyr(min(r['rpm'], rpm1))) for r in seg],
                       '#5b6670', 1.4))
        s.append(_path([(fx(r['t']), fyi(min(r['inj'], inj1))) for r in seg],
                       '#c2410c', 2.2))
        s.append(_txt(L + PW / 2, T - 26, ttl, 13, '#1c1c1c', anchor='middle', weight='600'))
        s.append(_txt(L + PW / 2, T - 10, note, 11, anchor='middle'))
        s.append(_txt(L + PW / 2, H - 14, '経過 [秒]', 11.5, anchor='middle'))
        lo = min(r['inj'] for r in seg)
        hi = max(r['inj'] for r in seg)
        s.append(_txt(L + PW - 8, T + 16, f'噴射 {lo:.0f} – {hi:.0f}', 11.5, '#c2410c',
                      anchor='end', weight='600'))
        s.append(_txt(L + PW - 8, T + 32,
                      f'回転 {min(r["rpm"] for r in seg):.0f} – {max(r["rpm"] for r in seg):.0f}',
                      11.5, '#5b6670', anchor='end'))
        if i == 1:
            s.append(_txt(L + PW - 8, T + 50,
                          f'車速 {seg[0]["spd"]:.0f} → {seg[-1]["spd"]:.0f} km/h', 11.5,
                          '#5b6670', anchor='end'))
    for v in range(0, inj1 + 1, 500):
        y = H - B - v / inj1 * (H - T - B)
        s.append(_txt(48, y + 4, f'{v}', 11, '#c2410c', anchor='end'))
    for v in range(0, rpm1 + 1, 2000):
        y = H - B - v / rpm1 * (H - T - B)
        s.append(_txt(W - 48, y + 4, f'{v}', 11, '#5b6670'))
    s.append(f'<text x="14" y="{(T+H-B)/2:.0f}" font-size="12" fill="#c2410c" '
             f'text-anchor="middle" transform="rotate(-90 14 {(T+H-B)/2:.0f})">'
             f'噴射時間（生値）</text>')
    s.append(f'<text x="{W-13}" y="{(T+H-B)/2:.0f}" font-size="12" fill="#5b6670" '
             f'text-anchor="middle" transform="rotate(90 {W-13} {(T+H-B)/2:.0f})">'
             f'回転数 [rpm]</text>')
    _save(path, s)


# ── figH 車速バイトと GPS ──────────────────────────────────
def fig_speed(path, pairs):
    """`[17]` は標準層の `0D` と同じ信号。帯ごとの比で見る。"""
    W, H = 720, 460
    L, Rm, T, B = 58, 186, 30, 54
    hi = 70
    fx = lambda v: L + v / hi * (W - L - Rm)
    fy = lambda v: H - B - v / hi * (H - T - B)
    s = [_hdr(W, H, '車速バイトと GPS')]
    for v in range(0, hi + 1, 20):
        s.append(_line(fx(v), T, fx(v), H - B, C_GR, 1, op=0.18))
        s.append(_line(L, fy(v), W - Rm, fy(v), C_GR, 1, op=0.18))
        s.append(_txt(fx(v), H - B + 17, f'{v}', 11.5, anchor='middle'))
        s.append(_txt(L - 8, fy(v) + 4, f'{v}', 11.5, anchor='end'))
    s.append(_txt((L + W - Rm) / 2, H - 14, 'GPS 速度 [km/h]', 12.5, anchor='middle'))
    s.append(f'<text x="15" y="{(T+H-B)/2:.0f}" font-size="12.5" fill="{C_TX}" '
             f'text-anchor="middle" transform="rotate(-90 15 {(T+H-B)/2:.0f})">'
             f'独自層の車速バイト `[17]` [km/h]</text>'.replace('`', ''))

    s.append(_path([(fx(0), fy(0)), (fx(hi), fy(hi))], C_AX, 1.4, dash='4 4'))
    s.append(_txt(fx(46), fy(46) - 7, '1 : 1', 11, C_AX))
    pred = 14 / 15
    s.append(_path([(fx(0), fy(0)), (fx(hi), fy(hi * pred))], '#2a78d6', 2.0))
    s.append(_txt(fx(hi) - 4, fy(hi * pred) + 16, f'丁数比 14/15 = {pred:.4f}', 11,
                  '#2a78d6', anchor='end', weight='600'))
    for g, v in pairs:
        s.append(_dot(fx(g), fy(v), 2.0, '#5b6670', 0.3))

    # 帯ごとの中央比
    bands, y = [], T + 14
    for lo in range(10, hi, 10):
        sel = [(g, v) for g, v in pairs if lo <= g < lo + 10]
        if len(sel) < 20:
            continue
        med = st.median(v / g for g, v in sel)
        bands.append((lo, len(sel), med))
        s.append(_dot(fx(lo + 5), fy((lo + 5) * med), 5.0, '#c2410c', 0.95))
    tx = W - Rm + 14
    s.append(_txt(tx, y, '帯ごとの `[17]`/GPS'.replace('`', ''), 12.5, weight='600'))
    y += 22
    s.append(_txt(tx, y, 'GPS 帯', 11)); s.append(_txt(tx + 92, y, 'n', 11, anchor='end'))
    s.append(_txt(tx + 152, y, '中央比', 11, anchor='end'))
    y += 17
    for lo, n, med in bands:
        s.append(_txt(tx, y, f'{lo}–{lo+10}', 11.5))
        s.append(_txt(tx + 92, y, f'{n}', 11.5, anchor='end'))
        s.append(_txt(tx + 152, y, f'{med:.4f}', 11.5, anchor='end', weight='600'))
        y += 17
    allmed = st.median(v / g for g, v in pairs)
    y += 10
    s.append(_txt(tx, y, f'全体の中央比 {allmed:.4f}', 11.5, '#c2410c', weight='600'))
    y += 24
    for ln in ('標準層 `0D`/GPS の', '既知 0.933〜0.942 と', '同じ範囲に入る。',
               '', '**別の信号ではない。**', '`0D` の校正を', 'そのまま継承できる。'):
        if ln:
            s.append(_txt(tx, y, ln.replace('`', '').replace('**', ''), 11,
                          weight='600' if '**' in ln else 'normal'))
        y += 15
    _save(path, s)



# ── figB 基板のブロック図 ──────────────────────────────────
C_PWR, C_RAIL, C_SIG = '#eda100', '#1baf7a', '#2a78d6'
C_BOX, C_EDGE = '#f2f4f6', '#b8c0c8'


def _box(x, y, w, h, lines, edge=C_EDGE, fill=C_BOX):
    """枠と中身。lines は (文字列, 大きさ, 色, 太さ) の列。"""
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="{fill}" '
           f'stroke="{edge}" stroke-width="1.4"/>']
    ty = y + 10
    for txt, size, col, wt in lines:
        ty += size + 4
        out.append(_txt(x + w / 2, ty, txt, size, col, anchor='middle', weight=wt))
    return out


def _arrow(x1, y1, x2, y2, col, w=2.2, head=True):
    out = [_line(x1, y1, x2, y2, col, w)]
    if head:
        dx, dy = x2 - x1, y2 - y1
        n = max((dx * dx + dy * dy) ** 0.5, 1e-6)
        ux, uy = dx / n, dy / n
        px, py = -uy, ux
        out.append(f'<path d="M{x2:.1f},{y2:.1f} L{x2-7*ux+4*px:.1f},{y2-7*uy+4*py:.1f} '
                   f'L{x2-7*ux-4*px:.1f},{y2-7*uy-4*py:.1f} Z" fill="{col}"/>')
    return out


def fig_block(path):
    """`hardware/netlist.md` から起こしたブロック図。電源 1 系統と K 線の折り返しが要点。"""
    W, H = 880, 512
    s = [_hdr(W, H, '基板のブロック図')]

    # ── 12V の経路 ──
    s += _arrow(150, 300, 186, 300, C_PWR, 2.6, head=False)
    s += _arrow(186, 300, 186, 100, C_PWR, 2.6, head=False)
    s += _arrow(186, 100, 200, 100, C_PWR, 2.6)
    s += _arrow(304, 100, 420, 100, C_PWR, 2.6)
    s.append(_txt(356, 90, 'VIN', 10.5, C_PWR, anchor='end', weight='600'))
    s += _arrow(362, 60, 362, 100, C_PWR, 1.6, head=False)
    s += _arrow(362, 100, 362, 330, C_PWR, 1.6, head=False)   # R7 の枝
    s += _arrow(612, 100, 660, 100, C_PWR, 2.6, head=False)

    # ── 3.3V レール ──
    s += _arrow(660, 100, 660, 205, C_RAIL, 2.4, head=False)
    s += _arrow(486, 205, 712, 205, C_RAIL, 2.4, head=False)
    s += _arrow(500, 205, 500, 290, C_RAIL, 2.0)
    s += _arrow(700, 205, 700, 262, C_RAIL, 2.0)
    s.append(_txt(490, 197, '3.3V 1 系統（レベルシフト無し）', 10.5, C_RAIL, weight='600'))

    # ── K-Line と信号 ──
    s += _arrow(150, 330, 420, 330, C_SIG, 2.6)
    s.append(_txt(230, 322, 'K-Line', 10.5, C_SIG, weight='600'))
    s.append(f'<circle cx="362" cy="330" r="3.6" fill="{C_PWR}"/>')   # R7 が K を吊る点
    s += _arrow(580, 318, 650, 318, C_SIG, 2.0)
    s += _arrow(650, 350, 580, 350, C_SIG, 2.0)
    s.append(_txt(615, 310, 'TX ← IO17', 10, C_SIG, anchor='middle'))
    s.append(_txt(615, 366, 'RX → IO18', 10, C_SIG, anchor='middle'))
    s += _arrow(700, 394, 700, 412, C_SIG, 1.8, head=False)
    s += _arrow(700, 412, 505, 412, C_SIG, 1.8, head=False)
    s += _arrow(505, 412, 505, 432, C_SIG, 1.8)
    s += _arrow(790, 394, 790, 432, C_SIG, 1.8)

    # ── 箱 ──
    s += _box(24, 186, 126, 168, [])
    s.append(_txt(87, 206, '車両 4P カプラ', 12, '#1c1c1c', anchor='middle', weight='600'))
    s.append(_txt(87, 221, '住友 6187-4441', 9.5, anchor='middle'))
    for i, (lab, col) in enumerate((('1  GND', C_TX), ('2  SCS 未使用', C_TX),
                                    ('3  +12V（IG 連動）', C_PWR), ('4  K-Line', C_SIG))):
        s.append(_txt(36, 246 + i * 30, lab, 10.5, col,
                      weight='600' if col != C_TX else 'normal'))
    s += _box(200, 78, 104, 44, [('D1  SS36', 11, '#1c1c1c', '600'),
                                 ('逆接保護', 10, C_TX, 'normal')])
    s += _box(296, 18, 136, 42, [('D2 SMBJ18A（TVS）', 10.5, '#1c1c1c', '600'),
                                 ('C1 C2 平滑・バルク', 9.5, C_TX, 'normal')])
    s += _box(420, 72, 192, 56, [('U1  AP63203WU-7 ＋ L1', 11, '#1c1c1c', '600'),
                                 ('12V → 3.3V 同期整流', 10, C_TX, 'normal')])
    s += _box(322, 222, 80, 32, [('R7 510Ω', 10.5, '#1c1c1c', '600')])
    s += _box(420, 290, 160, 88, [('U3  L9637D', 11.5, '#1c1c1c', '600'),
                                  ('K-Line トランシーバ', 10, C_TX, 'normal'),
                                  ('VS = 12V（バス側）', 10, C_PWR, 'normal'),
                                  ('VCC = 3.3V（ロジック）', 10, C_RAIL, 'normal')])
    s += _box(650, 262, 196, 132, [('U2  ESP32-S3-WROOM-1', 11.5, '#1c1c1c', '600'),
                                   ('N16R8', 10, C_TX, 'normal'),
                                   ('BLE  ——  スマホと転送', 10, C_TX, 'normal'),
                                   ('WiFi  ——  OTA', 10, C_TX, 'normal'),
                                   ('16MB  ——  LittleFS に記録', 10, C_TX, 'normal')])
    s += _box(420, 432, 170, 50, [('J3  書き込み 5P', 10.5, '#1c1c1c', '600'),
                                  ('圧入のみ・部品を載せない', 9.5, C_TX, 'normal')])
    s += _box(650, 432, 196, 50, [('J2  表示器 6P（未決）', 10.5, '#1c1c1c', '600'),
                                  ('I2C / SPI どちらでも挿せる', 9.5, C_TX, 'normal')])

    # ── 注記 ──
    s.append(_txt(24, 404, '50 × 40mm / 2 層 / 27 部品 19 品種 / 部品代 $8.32', 10.5,
                  '#1c1c1c', weight='600'))
    s.append(_txt(24, 420, 'JLCPCB で実装まで。手ハンダは J1 J2 だけ', 10.5))
    for i, ln in enumerate((
            'R7 が基板に載っているので、K を未接続のまま 12V を入れると',
            'K は 12V に吊られ、TX → K → RX が基板の中で閉じる。',
            '車両に挿さずに通信を確かめられる。')):
        s.append(_txt(24, 452 + i * 15, ln, 10, C_NG if i == 2 else C_TX,
                      weight='600' if i == 2 else 'normal'))

    # ── 凡例 ──
    for i, (col, lab) in enumerate(((C_PWR, '12V'), (C_RAIL, '3.3V'), (C_SIG, 'K-Line・信号'))):
        y = 24 + i * 17
        s.append(_line(24, y, 44, y, col, 3))
        s.append(_txt(49, y + 4, lab, 10, col, weight='600'))
    _save(path, s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--logs', default='private/logs')
    ap.add_argument('--out', default='docs')
    a = ap.parse_args()
    lg = a.logs

    fig_block(f'{a.out}/figB-block.svg')      # ログに依らない

    spec = (('1 本目 09-19 11:50', [f'{lg}/r260919_1150.bin']),
            ('2 本目 09-19 12:24', [f'{lg}/r260919_1224.bin']),
            ('3 本目 09-19 15:17', sorted(glob.glob(f'{lg}/auto0002_0*.bin'))))
    runs = [(n, judge(pub(load_run(p)))) for n, p in spec if all(os.path.exists(x) for x in p)]
    if len(runs) != 3:
        sys.exit('ログが足りない（private/logs に実走 3 本が要る）')
    two = runs[0][1] + runs[1][1]      # 真値突合はこの 2 本（gear.md と同じ）

    fig_drive(f'{a.out}/fig6-drive.svg', two)
    fig_band(f'{a.out}/fig7-band.svg', two)
    fig_tol(f'{a.out}/fig8-tolerance.svg', [r for _, rs in runs for r in rs])
    fig_gate(f'{a.out}/fig9-gate.svg', runs)

    probe = f'{lg}/probe.bin'
    if os.path.exists(probe):
        fig_scan(f'{a.out}/figA-tables.svg', scan_tables(probe))
        blip = [r for r in load_run([probe]) if 372 <= r['t'] <= 412]
        cut = [r for r in runs[2][1] if 774.0 <= r['t'] <= 784.0]
        fig_inj(f'{a.out}/figC-injection.svg', blip, cut)

    # `[17]` と GPS。**帯ごとの比で見る** —— 切片つきの最小二乗は 20km/h 未満の
    # GPS 雑音に引かれて実体の無い切片を出す（FINDINGS.md）
    pairs = []
    for _, paths in spec[:2]:
        rows, base = load_run(paths, with_base=True)
        gp = sorted(glob.glob(f'{lg}/gps_2026-09-19T02*.csv'))
        if not (base and gp):
            continue
        g = load_gps(gp[0])
        keys = [x[0] for x in g]
        for r in rows:
            if r['spd'] is None or r['spd'] < 5 or r['spd'] > SPD_MAX_PUB:
                continue
            m = gps_at(g, keys, base + r['t'])
            if m and m['speed_gps'] and m['speed_gps'] >= 5 \
                    and m['gps_acc'] is not None and m['gps_acc'] <= 15 \
                    and m['speed_gps'] <= SPD_MAX_PUB:
                pairs.append((m['speed_gps'], r['spd']))
    if pairs:
        fig_speed(f'{a.out}/figH-speed.svg', pairs)


if __name__ == '__main__':
    main()
