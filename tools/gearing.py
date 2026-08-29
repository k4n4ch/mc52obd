#!/usr/bin/env python3
"""CB250R（MC52）フロントスプロケット 14T / 15T の走行余力比較。

GEARING.md の全数値を再現する。実測ログとの突合も行う。

    python3 tools/gearing.py            # 全表
    python3 tools/gearing.py --verify   # 実測突合のみ
"""
import argparse, csv, glob, math, statistics as st

# ---- 同定（諸元・実測で検証済み）----------------------------------------
# 2018 年式 = 2BK-MC52。2022-07 の 8BK-MC52 は出力/トルクの発生回転数が異なる
GEAR = {1: 3.416, 2: 2.250, 3: 1.650, 4: 1.350, 5: 1.166, 6: 1.038}
PRIMARY = 2.807                # 一次減速比（二次減速比 2.571 = 36/14 が標準）
REAR = 36                      # リアスプロケット（MC52 は 36T 固定、標準フロント 14T）
CIRC = math.pi * (17 * 25.4 + 2 * 150 * 0.60) / 1000   # 150/60R17 = 1.9222 m
CURB = 144.0                   # 車両重量 kg（諸元）

# ---- 推定（諸元 2 点からの補間形）----------------------------------------
# 2BK-MC52 の諸元 20 kW / 9000 rpm、23 N·m / 8000 rpm に整合させたトルク曲線
TORQUE = {3000: 17.5, 4000: 19.5, 5000: 20.8, 6000: 21.8, 7000: 22.5,
          8000: 23.0, 8500: 22.3, 9000: 21.2, 9500: 19.8, 10500: 17.0}

# ---- 仮定（外部から与える値）----------------------------------------------
RIDER = 75.0     # kg（乗員＋装備）
MASS = CURB + RIDER
CRR  = 0.020     # 転がり抵抗係数
RHO  = 1.20      # kg/m^3
CDA  = 0.60      # m^2（直立ネイキッド＋乗員）

LUG_RPM  = 3900  # トップギアで粘れる下限とみなす回転数
REV_LIMIT = 10500


def torque(rpm):
    ks = sorted(TORQUE)
    if rpm <= ks[0]:  return TORQUE[ks[0]]
    if rpm >= ks[-1]: return TORQUE[ks[-1]]
    for a, b in zip(ks, ks[1:]):
        if a <= rpm <= b:
            return TORQUE[a] + (TORQUE[b] - TORQUE[a]) * (rpm - a) / (b - a)


def reduction(front, gear):
    return PRIMARY * GEAR[gear] * REAR / front


def rpm_at(v_kmh, front, gear):
    return v_kmh * 1000 / 60 / CIRC * reduction(front, gear)


def v_at(rpm, front, gear):
    return rpm * 60 * CIRC / 1000 / reduction(front, gear)


def p_required(v_kmh, cda=CDA, headwind=0.0):
    v = v_kmh / 3.6
    va = v + headwind
    return (0.5 * RHO * cda * va * va + CRR * MASS * 9.81) * v / 1000


def state(v_kmh, front, gear, cda=CDA, headwind=0.0):
    """(rpm, 出力kW, 余裕kW, 登坂%, トルク使用率%) を返す。"""
    r = rpm_at(v_kmh, front, gear)
    avail = torque(r) * r * 0.10472 / 1000
    req = p_required(v_kmh, cda, headwind)
    surplus = avail - req
    grade = surplus * 1000 / (v_kmh / 3.6) / (MASS * 9.81) * 100
    used = req * 1000 / (r * 0.10472) / torque(r) * 100
    return r, avail, surplus, grade, used


def top_of_range(front, gear, ref):
    """余裕が ref kW を下回る直前の車速。"""
    ok = [v * 0.25 for v in range(200, 700) if state(v * 0.25, front, gear)[2] >= ref]
    return max(ok) if ok else float('nan')


# ---------------------------------------------------------------- 実測突合
def verify():
    """ログの 6 速定常点と計算値を突合する（フロント 15T で走行）。"""
    K, TOL = 1.0148, 0.05           # ギア判定の較正係数と許容幅
    GF = 1 / 0.935                  # OBD 車速 -> 実車速（0D/GPS の実測値）
    R = {n: PRIMARY * GEAR[n] * (REAR / 14) / (CIRC * 60 / 1000) for n in GEAR}

    def gear_of(rpm, spd):
        if spd <= 1 or rpm < 500:
            return None
        ratio, best = rpm / spd, None
        for n in R:
            e = abs(ratio / (K * R[n]) - 1)
            if e < TOL and (best is None or e < best[1]):
                best = (n, e)
        return best[0] if best else None

    buckets = {}
    files = sorted(glob.glob('private/*.csv'))
    for f in files:
        c = []
        for r in csv.DictReader(open(f)):
            try:
                c.append((float(r['t_sec']), float(r['rpm']), float(r['speed_obd']),
                          float(r['throttle']), float(r['load'])))
            except (ValueError, KeyError):
                pass
        for i in range(2, len(c) - 2):
            t, rpm, spd, thr, ld = c[i]
            if gear_of(rpm, spd) != 6:
                continue
            win = c[i - 2:i + 3]
            if win[-1][0] - win[0][0] > 4:        # 連続していること
                continue
            sp = [w[2] for w in win]
            if max(sp) - min(sp) > 2:             # 定常（±2 km/h 以内）
                continue
            buckets.setdefault(int(spd * GF // 5) * 5, []).append((rpm, thr, ld))

    if not buckets:
        print(f'ログが見つからない（探索先 private/*.csv、{len(files)} 件）')
        return
    print('## 実測との突合（15T・6 速・定常）\n')
    print(f'{"実車速":>10} {"n":>4} {"実測rpm":>8} {"計算rpm":>8} {"差":>7} '
          f'{"thr%":>7} {"load%":>7}')
    for b in sorted(buckets):
        a = buckets[b]
        if len(a) < 4:
            continue
        v = b + 2.5
        m = st.median(x[0] for x in a)
        calc = rpm_at(v, 15, 6)
        print(f'{b:>4}-{b+5:<5} {len(a):>4} {m:>8.0f} {calc:>8.0f} '
              f'{(m/calc-1)*100:>+6.1f}% {st.median(x[1] for x in a):>7.1f} '
              f'{st.median(x[2] for x in a):>7.1f}')


# ---------------------------------------------------------------- 各表
def table_ladder():
    print('## 総減速比\n')
    print(f'{"段":>3} {"14T":>9} {"15T":>9} {"段間比":>9}')
    for n in GEAR:
        step = f'{(GEAR[n]/GEAR[n+1]-1)*100:8.1f}%' if n < 6 else ' ' * 9
        print(f'{n:>3} {reduction(14,n):>9.3f} {reduction(15,n):>9.3f} {step}')
    print(f'\n15T 5 速 / 14T 6 速 = {reduction(15,5)/reduction(14,6):.4f} '
          f'({(reduction(15,5)/reduction(14,6)-1)*100:+.1f}%)')
    print(f'15T 6 速 / 14T 6 速 = {reduction(15,6)/reduction(14,6):.4f} '
          f'({(reduction(15,6)/reduction(14,6)-1)*100:+.1f}%)')
    shift = 1 - reduction(15, 6) / reduction(14, 6)
    for a, b in ((5, 6), (1, 2)):
        step = GEAR[a] / GEAR[b] - 1
        print(f'  丁数変更 {shift*100:.1f}% は {a}-{b} 段間 {step*100:.1f}% の '
              f'{shift/step:.2f} 段ぶん')


def table_surplus():
    cols = [(14, 6), (15, 6), (15, 5)]
    print('\n## 走行余力\n')
    print(f'{"車速":>4} |' + ''.join(f'{f"{f}T {g}速":^30}|' for f, g in cols)
          + f'{"所要":>7}')
    print(f'{"":4} |' + ''.join(f'{"rpm":>7}{"余裕kW":>9}{"登坂%":>7}{"使用率":>7}|'
                                for _ in cols) + f'{"kW":>7}')
    for v in (60, 70, 80, 90, 100, 110, 120, 130):
        line = f'{v:>4} |'
        for f, g in cols:
            r, _, s, gr, used = state(v, f, g)
            line += f'{r:>7.0f}{s:>9.1f}{gr:>7.1f}{used:>6.0f}%|'
        print(line + f'{p_required(v):>7.1f}')


def table_window():
    ref = state(120, 14, 6)[2]
    print(f'\n## 6 速の実用窓（上端は余力が {ref:.2f} kW = 14T@120km/h を切る点）\n')
    print(f'{"":9}{"下端":>10}{"上端":>10}{"窓幅":>9}')
    for f in (14, 15):
        lo, hi = v_at(LUG_RPM, f, 6), top_of_range(f, 6, ref)
        print(f'{f}T 6 速 {lo:>8.0f}   {hi:>8.0f}   {hi-lo:>7.0f} km/h')
    lo, hi = v_at(LUG_RPM, 15, 5), top_of_range(15, 5, ref)
    print(f'15T 5 速 {lo:>8.0f}   {hi:>8.0f}   {hi-lo:>7.0f} km/h')


def table_wind():
    print('\n## 向かい風で 6 速を維持できる上限車速\n')
    print(f'{"向かい風":>9}{"14T 6速":>10}{"15T 6速":>10}{"15T 5速":>10}')
    for w in (0, 3, 6, 10):
        out = []
        for f, g in ((14, 6), (15, 6), (15, 5)):
            ok = [v * 0.5 for v in range(120, 320)
                  if state(v * 0.5, f, g, headwind=w)[2] >= 0]
            out.append(max(ok) if ok else float('nan'))
        print(f'{w:>6} m/s{out[0]:>10.0f}{out[1]:>10.0f}{out[2]:>10.0f}')


def table_sensitivity():
    print('\n## CdA 感度（100 km/h・6 速の余裕 kW）\n')
    print(f'{"CdA":>6}{"所要kW":>9}{"14T":>8}{"15T":>8}')
    for cda in (0.55, 0.60, 0.65, 0.70):
        a = state(100, 14, 6, cda=cda)[2]
        b = state(100, 15, 6, cda=cda)[2]
        print(f'{cda:>6.2f}{p_required(100,cda):>9.1f}{a:>8.1f}{b:>8.1f}')
    print('\n## レブリミット到達車速\n')
    for f, g in ((14, 6), (15, 6), (15, 5)):
        print(f'  {f}T {g} 速: {v_at(REV_LIMIT, f, g):.0f} km/h')

# ---------------------------------------------------------------- 図の生成
# GitHub の light / dark どちらでも読めるよう中間色で塗る（メディアクエリは
# <img> 経由だと効かないことがあるため使わない）
C_AX, C_TX, C_GR = '#9aa4ae', '#767f89', '#808a94'
C14, C15_6, C15_5, C_RES = '#3b82c4', '#e07b39', '#2fa363', '#9aa4ae'
FONT = "-apple-system,'Helvetica Neue',Arial,'Hiragino Sans',Meiryo,sans-serif"


def _hdr(w, h, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'width="{w}" height="{h}" font-family="{FONT}" role="img">'
            f'<title>{title}</title>')


def _txt(x, y, s, size=12, fill=None, anchor='start', weight='normal'):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill or C_TX}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{s}</text>')


def _path(pts, color, width=2.0, dash=None):
    d = 'M' + ' L'.join(f'{x:.1f},{y:.1f}' for x, y in pts)
    da = f' stroke-dasharray="{dash}"' if dash else ''
    return (f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"'
            f' stroke-linejoin="round" stroke-linecap="round"{da}/>')


def fig_power(path):
    """出力‐走行抵抗線図。余力＝縦の隙間、最高速＝交点。"""
    W, H = 760, 460
    L, R, T, B = 62, 34, 26, 52
    x0, x1, y0, y1 = 50, 145, 0, 22
    fx = lambda v: L + (v - x0) / (x1 - x0) * (W - L - R)
    fy = lambda v: H - B - (v - y0) / (y1 - y0) * (H - T - B)
    s = [_hdr(W, H, '出力‐走行抵抗線図')]

    for v in range(60, 145, 20):
        s.append(f'<line x1="{fx(v):.1f}" y1="{T}" x2="{fx(v):.1f}" y2="{H-B}" '
                 f'stroke="{C_GR}" stroke-width="1" opacity="0.22"/>')
        s.append(_txt(fx(v), H - B + 18, f'{v}', 12, anchor='middle'))
    for p_ in range(0, 23, 5):
        s.append(f'<line x1="{L}" y1="{fy(p_):.1f}" x2="{W-R}" y2="{fy(p_):.1f}" '
                 f'stroke="{C_GR}" stroke-width="1" opacity="0.22"/>')
        s.append(_txt(L - 8, fy(p_) + 4, f'{p_}', 12, anchor='end'))
    s.append(_txt((L + W - R) / 2, H - 14, '車速 [km/h]', 12.5, anchor='middle'))
    s.append(f'<text x="16" y="{(T+H-B)/2:.0f}" font-size="12.5" fill="{C_TX}" '
             f'text-anchor="middle" transform="rotate(-90 16 {(T+H-B)/2:.0f})">出力 [kW]</text>')

    # 走行抵抗（平坦・勾配3%・5%）。左端で分離しているのでそちらに注記
    for g, dash, lab in ((5, '2 3', '勾配 5%'), (3, '5 4', '勾配 3%'), (0, None, '平坦')):
        pts = []
        for i in range(int(x0), int(x1) + 1):
            v = i / 3.6
            pw = (0.5 * RHO * CDA * v * v + CRR * MASS * 9.81
                  + MASS * 9.81 * g / 100) * v / 1000
            if pw <= y1: pts.append((fx(i), fy(pw)))
        s.append(_path(pts, C_RES, 1.9 if g == 0 else 1.3, dash))
    s.append(_txt(fx(63), fy(1.0), '走行抵抗　平坦 / 勾配3% / 5%', 11.5, C_RES))

    # 各段の出力曲線
    tops, dots = [], []
    for (f, gr), col, lab in (((14, 6), C14, '14T 6速'), ((15, 6), C15_6, '15T 6速'),
                              ((15, 5), C15_5, '15T 5速')):
        pts, top = [], None
        for i in range(int(x0), int(x1) + 1):
            r = rpm_at(i, f, gr)
            if r > REV_LIMIT: break
            pw = torque(r) * r * 0.10472 / 1000
            pts.append((fx(i), fy(min(pw, y1))))
            if pw >= p_required(i): top = i
        s.append(_path(pts, col, 2.4))
        if top:
            tops.append(top)
            dots.append((fx(top), fy(p_required(top)), col))
    # 14T 6速 と 15T 5速 は同じ点に落ちるので、外側に大きく描いてから重ねる
    for r_, (dx, dy, col) in zip((7.0, 4.5, 4.5), reversed(dots)):
        s.append(f'<circle cx="{dx:.1f}" cy="{dy:.1f}" r="{r_}" fill="{col}"/>')

    # 凡例（左上の空き）
    lx, ly = fx(52), fy(21.2)
    for i, (col, lab) in enumerate(((C14, '14T 6速'), (C15_6, '15T 6速'), (C15_5, '15T 5速'))):
        y = ly + i * 19
        s.append(f'<line x1="{lx:.1f}" y1="{y:.1f}" x2="{lx+26:.1f}" y2="{y:.1f}" '
                 f'stroke="{col}" stroke-width="2.6"/>')
        s.append(_txt(lx + 33, y + 4, lab, 12.5, col, weight='600'))

    # 100km/h での余力
    va = 100
    yr = fy(p_required(va))
    y14 = fy(torque(rpm_at(va, 14, 6)) * rpm_at(va, 14, 6) * 0.10472 / 1000)
    y15 = fy(torque(rpm_at(va, 15, 6)) * rpm_at(va, 15, 6) * 0.10472 / 1000)
    s.append(f'<line x1="{fx(va):.1f}" y1="{yr:.1f}" x2="{fx(va):.1f}" y2="{y14:.1f}" '
             f'stroke="{C_TX}" stroke-width="1.3"/>')
    for yy in (yr, y14, y15):
        s.append(f'<line x1="{fx(va)-5:.1f}" y1="{yy:.1f}" x2="{fx(va)+5:.1f}" y2="{yy:.1f}" '
                 f'stroke="{C_TX}" stroke-width="1.3"/>')
    s.append(_txt(fx(va) - 10, (yr + y14) / 2 + 4, 'この隙間が余力', 12, anchor='end',
                  weight='600'))

    # 最高速
    if tops:
        s.append(f'<line x1="{fx(min(tops)):.1f}" y1="{fy(y1):.1f}" '
                 f'x2="{fx(min(tops)):.1f}" y2="{fy(p_required(min(tops)))-8:.1f}" '
                 f'stroke="{C_TX}" stroke-width="1" stroke-dasharray="3 3"/>')
        s.append(_txt(fx(min(tops)) - 10, fy(21.5), '●＝走行抵抗との交点＝最高速', 12,
                      anchor='end', weight='600'))
        s.append(_txt(fx(min(tops)) - 10, fy(20.4),
                      f'3本とも {min(tops):.0f}–{max(tops):.0f} km/h に集まる', 11.5,
                      anchor='end'))
    s.append('</svg>')
    open(path, 'w', encoding='utf-8').write('\n'.join(s))


def fig_window(path):
    """6速の実用窓。両端を決める要因が違うことを示す。"""
    W, H = 760, 280
    L, R, T = 96, 92, 46
    x0, x1 = 50, 135
    fx = lambda v: L + (v - x0) / (x1 - x0) * (W - L - R)
    s = [_hdr(W, H, '6速の実用窓')]
    for v in range(50, 136, 10):
        s.append(f'<line x1="{fx(v):.1f}" y1="{T-10}" x2="{fx(v):.1f}" y2="{T+150}" '
                 f'stroke="{C_GR}" stroke-width="1" opacity="0.22"/>')
        s.append(_txt(fx(v), T - 18, f'{v}', 12, anchor='middle'))
    s.append(_txt(fx(92), T - 34, '車速 [km/h]', 12.5, anchor='middle'))

    ref = state(120, 14, 6)[2]
    rows = [((14, 6), '14T 6速', C14), ((15, 6), '15T 6速', C15_6), ((15, 5), '15T 5速', C15_5)]
    for i, ((f, g), lab, col) in enumerate(rows):
        lo, hi = v_at(LUG_RPM, f, g), top_of_range(f, g, ref)
        y = T + 12 + i * 44
        s.append(f'<rect x="{fx(lo):.1f}" y="{y}" width="{fx(hi)-fx(lo):.1f}" height="26" '
                 f'rx="4" fill="{col}" opacity="0.82"/>')
        s.append(_txt(L - 12, y + 18, lab, 13, col, anchor='end', weight='600'))
        s.append(_txt(fx(hi) + 10, y + 18, f'{lo:.0f}–{hi:.0f}（幅 {hi-lo:.0f}）', 12))
    yb = T + 12 + 3 * 44
    s.append(f'<line x1="{fx(60):.1f}" y1="{T+2}" x2="{fx(60):.1f}" y2="{yb+6}" '
             f'stroke="{C_TX}" stroke-width="1" stroke-dasharray="3 3"/>')
    s.append(f'<line x1="{fx(120):.1f}" y1="{T+2}" x2="{fx(120):.1f}" y2="{yb+6}" '
             f'stroke="{C_TX}" stroke-width="1" stroke-dasharray="3 3"/>')
    s.append(_txt(fx(60), yb + 22, '下端は回転数で決まる', 11.5, anchor='middle'))
    s.append(_txt(fx(60), yb + 38, '（3,900rpm に達する車速）', 11, anchor='middle'))
    s.append(_txt(fx(120), yb + 22, '上端は出力で決まる', 11.5, anchor='middle'))
    s.append(_txt(fx(120), yb + 38, f'（余力が {ref:.1f}kW を切る車速）', 11, anchor='middle'))
    s.append('</svg>')
    open(path, 'w', encoding='utf-8').write('\n'.join(s))


def fig_ladder(path):
    """総減速比のラダー。一様シフトと 15T5速≒14T6速 を同時に示す。"""
    import math as _m
    W, H = 760, 320
    L, R, T = 84, 104, 74
    lo, hi = 6.75, 26.0
    fx = lambda r: L + (_m.log(hi) - _m.log(r)) / (_m.log(hi) - _m.log(lo)) * (W - L - R)
    s = [_hdr(W, H, '総減速比のラダー')]
    for r in (25, 20, 16, 12, 10, 8, 7):
        s.append(f'<line x1="{fx(r):.1f}" y1="{T-12}" x2="{fx(r):.1f}" y2="{T+96}" '
                 f'stroke="{C_GR}" stroke-width="1" opacity="0.2"/>')
        s.append(_txt(fx(r), T - 20, f'{r}', 11.5, anchor='middle'))
    s.append(_txt((L + W - R) / 2, T - 42, '総減速比（対数軸）', 12.5, anchor='middle'))
    s.append(_txt(L, T - 42, '←ロー', 11.5))
    s.append(_txt(W - R, T - 42, 'ハイ→', 11.5, anchor='end'))

    for i, f in enumerate((14, 15)):
        y = T + 16 + i * 52
        col = C14 if f == 14 else C15_6
        s.append(_txt(L - 14, y + 5, f'{f}T', 13.5, col, anchor='end', weight='600'))
        s.append(f'<line x1="{fx(reduction(f,1)):.1f}" y1="{y}" '
                 f'x2="{fx(reduction(f,6)):.1f}" y2="{y}" stroke="{col}" '
                 f'stroke-width="1.4" opacity="0.5"/>')
        for n in GEAR:
            x = fx(reduction(f, n))
            hl = (f == 15 and n == 5) or (f == 14 and n == 6)
            s.append(f'<circle cx="{x:.1f}" cy="{y}" r="{11 if hl else 9}" fill="{col}" '
                     f'opacity="{1.0 if hl else 0.8}"/>')
            s.append(f'<text x="{x:.1f}" y="{y+4:.0f}" font-size="11" fill="#ffffff" '
                     f'text-anchor="middle" font-weight="600">{n}</text>')

    # 一様シフト
    ya, yb = T + 16, T + 68
    for n in (1, 2, 3, 4):
        xa, xb = fx(reduction(14, n)), fx(reduction(15, n))
        s.append(f'<line x1="{xa:.1f}" y1="{ya+12}" x2="{xb:.1f}" y2="{yb-12}" '
                 f'stroke="{C_TX}" stroke-width="1" stroke-dasharray="2 3" opacity="0.75"/>')
    s.append(_txt(fx(14.0), T + 46, '全段が一様に 6.7% ハイギア', 11.5, weight='600'))

    # 15T の 6速は 14T に無い高さ（右外に出す）
    x6t = fx(reduction(15, 6))
    s.append(f'<line x1="{x6t:.1f}" y1="{T+68}" x2="{W-R+16:.1f}" y2="{T+68}" '
             f'stroke="{C15_6}" stroke-width="1" stroke-dasharray="3 3"/>')
    s.append(_txt(W - R + 20, T + 64, '14T に無い', 11, C15_6))
    s.append(_txt(W - R + 20, T + 78, '高さ', 11, C15_6))

    # 15T5速 ≒ 14T6速
    x5, x6 = fx(reduction(15, 5)), fx(reduction(14, 6))
    ym = T + 122
    s.append(f'<path d="M{x6:.1f},{T+29} L{x6:.1f},{ym} M{x5:.1f},{T+81} L{x5:.1f},{ym}" '
             f'stroke="{C_TX}" stroke-width="1.2"/>')
    s.append(f'<line x1="{x6:.1f}" y1="{ym}" x2="{x5:.1f}" y2="{ym}" '
             f'stroke="{C_TX}" stroke-width="1.2"/>')
    cx = (x5 + x6) / 2
    s.append(_txt(cx, ym + 20, '15T 5速 は 14T 6速 の 4.8% ロー', 12.5, anchor='middle',
                  weight='600'))
    s.append(_txt(cx, ym + 38, '＝ 14T 6速 の仕事をそのまま引き受ける', 11.5, anchor='middle'))
    s.append('</svg>')
    open(path, 'w', encoding='utf-8').write('\n'.join(s))


def fig_ranges(path):
    """各段が受け持てる車速範囲。14T と 15T を段ごとに対比する。"""
    W, H = 760, 456
    L, R, T = 66, 110, 54
    x0, x1 = 0, 155
    fx = lambda v: L + (v - x0) / (x1 - x0) * (W - L - R)
    ref = state(120, 14, 6)[2]

    def win(f, n):
        lo = v_at(LUG_RPM, f, n)
        rev, pw = v_at(9000, f, n), top_of_range(f, n, ref)
        return lo, min(rev, pw), rev, pw < rev

    s = [_hdr(W, H, '各段が受け持てる車速範囲')]
    for v in range(0, 156, 20):
        s.append(f'<line x1="{fx(v):.1f}" y1="{T-14}" x2="{fx(v):.1f}" y2="{T+6*54-16}" '
                 f'stroke="{C_GR}" stroke-width="1" opacity="0.2"/>')
        s.append(_txt(fx(v), T - 22, f'{v}', 11.5, anchor='middle'))
    s.append(_txt((L + W - R) / 2, T - 40, '車速 [km/h]', 12.5, anchor='middle'))

    # 凡例（下端）
    ly = H - 44
    s.append(f'<rect x="{L}" y="{ly-9}" width="22" height="11" rx="2" fill="{C_TX}" '
             f'opacity="0.75"/>')
    s.append(_txt(L + 28, ly, '実用範囲', 11.5))
    s.append(f'<rect x="{L+92}" y="{ly-9}" width="22" height="11" rx="2" fill="{C_TX}" '
             f'opacity="0.2" stroke="{C_TX}" stroke-width="0.8" stroke-dasharray="2 2"/>')
    s.append(_txt(L + 120, ly, '回転数では届くが出力が足りない', 11.5))
    s.append(f'<circle cx="{L+330}" cy="{ly-3.5}" r="4" fill="{C_TX}"/>')
    s.append(_txt(L + 340, ly, '出力で頭打ち', 11.5))

    for n in GEAR:
        yb = T + (n - 1) * 54
        s.append(_txt(L - 14, yb + 22, f'{n}速', 13, anchor='end', weight='600'))
        for j, f in enumerate((14, 15)):
            col = C14 if f == 14 else C15_6
            lo, hi, rev, plim = win(f, n)
            y = yb + j * 20
            if plim:   # 回転では届く領域を淡色で
                s.append(f'<rect x="{fx(hi):.1f}" y="{y}" width="{fx(rev)-fx(hi):.1f}" '
                         f'height="15" rx="2" fill="{col}" opacity="0.16" stroke="{col}" '
                         f'stroke-width="0.8" stroke-dasharray="2 2"/>')
            s.append(f'<rect x="{fx(lo):.1f}" y="{y}" width="{fx(hi)-fx(lo):.1f}" '
                     f'height="15" rx="2.5" fill="{col}" opacity="0.85"/>')
            if plim:
                s.append(f'<circle cx="{fx(hi):.1f}" cy="{y+7.5}" r="4.2" fill="{col}" '
                         f'stroke="#ffffff" stroke-width="1"/>')
            s.append(_txt(fx(lo) - 5, y + 12, f'{f}T', 10.5, col, anchor='end'))
        wa = win(14, n)[1] - win(14, n)[0]
        wb = win(15, n)[1] - win(15, n)[0]
        s.append(_txt(W - R + 12, yb + 15, f'{wa:.0f} → {wb:.0f} km/h', 11.5))
        d = (wb / wa - 1) * 100
        s.append(_txt(W - R + 12, yb + 30, f'{d:+.0f}%', 12.5,
                      C15_6 if d < 0 else C_TX, weight='600'))
    s.append(_txt(L, H - 16,
                  '下限は 3,900rpm、上限は 9,000rpm と余力条件（3.9kW）の厳しい方', 11))
    s.append('</svg>')
    open(path, 'w', encoding='utf-8').write('\n'.join(s))


def make_figures(outdir='docs'):
    import os
    os.makedirs(outdir, exist_ok=True)
    fig_power(f'{outdir}/fig1-power.svg')
    fig_window(f'{outdir}/fig2-window.svg')
    fig_ladder(f'{outdir}/fig3-ladder.svg')
    fig_ranges(f'{outdir}/fig4-ranges.svg')
    for f in ('fig1-power', 'fig2-window', 'fig3-ladder', 'fig4-ranges'):
        print(f'{outdir}/{f}.svg')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--verify', action='store_true', help='実測突合のみ')
    ap.add_argument('--svg', action='store_true', help='docs/ に SVG 図を生成')
    a = ap.parse_args()
    if a.svg:
        make_figures()
    elif a.verify:
        verify()
    else:
        table_ladder(); table_surplus(); table_window()
        table_wind(); table_sensitivity(); print(); verify()
