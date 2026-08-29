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


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--verify', action='store_true', help='実測突合のみ')
    a = ap.parse_args()
    if a.verify:
        verify()
    else:
        table_ladder(); table_surplus(); table_window()
        table_wind(); table_sensitivity(); print(); verify()
