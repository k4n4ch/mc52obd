#!/usr/bin/env python3
"""走行ログから、ギヤ判定のスケール係数 k と判定窓を決める。

考え方
------
比 = rpm / 車速 は、engaged なギヤ n について

    比(n) = k * R(n),   R(n) = 一次 * 変速比(n) * 二次 / 円周[km] / 60

の形になる。k はタイヤ外径・摩耗・空気圧・速度計の系統誤差をまとめて吸収する
**唯一の未知数**。クラスタを 6 個独立に推定するのと違い、k を 1 個決めれば
全 6 速の窓が決まるので、較正走行で拾えなかったギヤも確定する。

さらに、k を当てはめた後に 6 個のクラスタが全部予測位置に乗るかを検査できる。
乗らなければ「単一の k では表せない」＝速度信号が非線形、と判定できる。

    python tools/gearcal.py <log.csv>
    python tools/gearcal.py <log.csv> --tol 4 --min-speed 15
"""

import argparse
import csv
import math
import sys

# ── 車両諸元（Honda factbook 2018-03、2BK-MC52）────────────
GEAR = {1: 3.416, 2: 2.250, 3: 1.650, 4: 1.350, 5: 1.166, 6: 1.038}
PRIMARY = 2.807
SECONDARY = 2.571
TIRE = "150/60R17"          # 後輪
RIM_IN, ASPECT, WIDTH = 17, 0.60, 150


def tire_circumference_m():
    d_mm = RIM_IN * 25.4 + 2 * WIDTH * ASPECT
    return math.pi * d_mm / 1000.0


def theoretical_ratios():
    """rpm / (km/h) の理論比を返す。"""
    circ = tire_circumference_m()
    out = {}
    for n, g in GEAR.items():
        total = PRIMARY * g * SECONDARY
        out[n] = total / (circ * 60 / 1000)
    return out


R = theoretical_ratios()
GEARS = sorted(R)


# ── ログ読み込み ─────────────────────────────────────────
# スマホアプリの CSV と Mac 側 logger.py の CSV の両方を受ける
COLMAP = [
    ("rpm", ["rpm", "0C_rpm"]),
    ("spd", ["speed_obd", "0D_speed"]),
    ("gps", ["speed_gps"]),
    ("t", ["t_sec"]),
]


def load(path):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        sys.exit("空のログ")
    cols = rows[0].keys()
    pick = {}
    for key, cands in COLMAP:
        for c in cands:
            if c in cols:
                pick[key] = c
                break
    for req in ("rpm", "spd", "t"):
        if req not in pick:
            sys.exit(f"必要な列が見つからない: {req} ({list(cols)})")

    out = []
    for r in rows:
        try:
            t = float(r[pick["t"]])
            rpm = float(r[pick["rpm"]]) if r[pick["rpm"]] != "" else None
            spd = float(r[pick["spd"]]) if r[pick["spd"]] != "" else None
        except ValueError:
            continue
        gps = None
        if "gps" in pick and r.get(pick["gps"]) not in (None, ""):
            try:
                gps = float(r[pick["gps"]])
            except ValueError:
                pass
        out.append({"t": t, "rpm": rpm, "spd": spd, "gps": gps})
    return out


# ── 定常点の抽出 ─────────────────────────────────────────
# rpm と車速は別リクエストで最短 158ms 離れて取得されるため、加速中は比が
# 歪む。回転変化率で定常点だけを残す。
def steady_points(rows, min_speed, max_drpm):
    pts = []
    prev = None
    for r in rows:
        if r["rpm"] is None or r["spd"] is None:
            continue
        if r["rpm"] < 500 or r["spd"] < min_speed:
            prev = r
            continue
        if prev and prev["rpm"] is not None:
            dt = r["t"] - prev["t"]
            if dt <= 0 or dt > 3.0:
                prev = r
                continue
            drpm = abs(r["rpm"] - prev["rpm"]) / dt
            if drpm > max_drpm:
                prev = r
                continue
        else:
            prev = r
            continue
        pts.append({"t": r["t"], "rpm": r["rpm"], "spd": r["spd"],
                    "gps": r["gps"], "ratio": r["rpm"] / r["spd"]})
        prev = r
    return pts


# ── k のフィット ─────────────────────────────────────────
# 比は乗法的なので対数空間で扱う。log(比) = log(k) + log(R(n)) となり、
# 各点は「等間隔でない櫛」の歯のどれかに乗る。櫛全体を平行移動させて
# 残差が最小になる位置を探す。外れ値（半クラ・シフト中）を引きずらない
# よう、残差は上限で頭打ちにする（robust）。
def fit_k(pts, k_lo=0.75, k_hi=1.25, steps=5000, cutoff_pct=8.0):
    if not pts:
        return None, []
    xs = [math.log(p["ratio"]) for p in pts]
    logR = [math.log(R[n]) for n in GEARS]
    cut = math.log(1 + cutoff_pct / 100.0)

    def cost(logk):
        s = 0.0
        for x in xs:
            d = min(abs(x - logk - lr) for lr in logR)
            s += min(d, cut) ** 2
        return s

    lo, hi = math.log(k_lo), math.log(k_hi)
    grid = [lo + (hi - lo) * i / (steps - 1) for i in range(steps)]
    costs = [cost(g) for g in grid]

    best_i = min(range(steps), key=lambda i: costs[i])
    # 局所最小を列挙して、最良解が十分に分離しているかを確認する
    minima = []
    for i in range(1, steps - 1):
        if costs[i] <= costs[i - 1] and costs[i] < costs[i + 1]:
            minima.append((costs[i], math.exp(grid[i])))
    minima.sort()
    return math.exp(grid[best_i]), minima[:4]


def assign(pts, k, tol_pct):
    """各点を最も近いギヤへ割り当てる。窓の外は None（不確定）。"""
    tol = tol_pct / 100.0
    for p in pts:
        best, bestd = None, None
        for n in GEARS:
            pred = k * R[n]
            d = abs(p["ratio"] / pred - 1.0)
            if bestd is None or d < bestd:
                best, bestd = n, d
        p["gear"] = best if bestd <= tol else None
        p["dev"] = bestd
    return pts


# ── 出力 ─────────────────────────────────────────────────
def hist(pts, k, width=54):
    """対数比のヒストグラム。櫛の位置に | を立てて重ね合わせる。"""
    if not pts:
        return
    xs = sorted(math.log(p["ratio"]) for p in pts)
    lo, hi = xs[0], xs[-1]
    span = hi - lo
    if span <= 0:
        return
    nb = 46
    bins = [0] * nb
    for x in xs:
        bins[min(nb - 1, int((x - lo) / span * nb))] = bins[min(nb - 1, int((x - lo) / span * nb))] + 1
    mx = max(bins) or 1
    marks = {}
    for n in GEARS:
        x = math.log(k * R[n])
        if lo <= x <= hi:
            marks[min(nb - 1, int((x - lo) / span * nb))] = n
    print("\n  比のヒストグラム（対数軸、↓が理論位置）")
    for i in range(nb):
        ratio = math.exp(lo + span * (i + 0.5) / nb)
        bar = "#" * int(bins[i] / mx * width)
        tag = f" ←{marks[i]}速" if i in marks else ""
        print(f"  {ratio:7.1f} |{bar:<{width}}|{bins[i]:5d}{tag}")


def linearity(pts):
    """0D と GPS 速度の比が速度域で一定か（単一 k が成り立つかの検査）。

    見るのは**水準ではなく速度域による変動**。比の水準はスプロケット丁数と
    タイヤ外径で動く（純正 14T なら ≒1.07、15T 化車なら ≒1.00）ので、
    1.0 から離れていること自体は異常ではない。詳細は FINDINGS.md。
    """
    have = [p for p in pts if p.get("gps") and p["gps"] > 5 and p["spd"] > 5]
    if len(have) < 20:
        print("\n  線形性検査: GPS 速度のある定常点が不足（%d 点）。判定不能" % len(have))
        return
    bands = [(0, 30), (30, 50), (50, 70), (70, 200)]
    print("\n  0D / GPS 速度比（単一 k の妥当性）")
    print("  ※ 見るのは速度域による変動。比の水準はスプロケ丁数とタイヤで動くので")
    print("     1.0 から離れていること自体は異常ではない")
    print("  速度域        n    比     ばらつき")
    vals = []
    for lo, hi in bands:
        sel = [p["spd"] / p["gps"] for p in have if lo <= p["gps"] < hi]
        if len(sel) < 5:
            continue
        m = sum(sel) / len(sel)
        sd = (sum((v - m) ** 2 for v in sel) / len(sel)) ** 0.5
        vals.append(m)
        print(f"  {lo:3d}-{hi:3d} km/h {len(sel):5d}  {m:5.3f}   ±{sd:.3f}")
    if len(vals) >= 2:
        drift = (max(vals) / min(vals) - 1) * 100
        print(f"  → 速度域による変動 {drift:.1f}%")
        if drift > 3:
            print("  → 3% を超える。速度信号が非線形の疑い。単一 k では窓がずれる")
        else:
            print("  → 一定とみなせる。単一 k で問題ない")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--tol", type=float, default=4.0, help="判定窓 ±%% (既定 4)")
    ap.add_argument("--min-speed", type=float, default=15.0, help="使う最低車速 km/h")
    ap.add_argument("--max-drpm", type=float, default=600.0, help="定常とみなす回転変化率 rpm/s")
    args = ap.parse_args()

    rows = load(args.csv)
    pts = steady_points(rows, args.min_speed, args.max_drpm)
    print(f"読み込み {len(rows)} 行 → 定常点 {len(pts)} 点 "
          f"(車速≧{args.min_speed:.0f}km/h, |drpm/dt|≦{args.max_drpm:.0f}rpm/s)")
    if len(pts) < 30:
        sys.exit("定常点が少なすぎる。各ギヤで数秒ずつ一定速度を保った走行が要る")

    k, minima = fit_k(pts)
    print(f"\nスケール係数 k = {k:.4f}")
    if len(minima) >= 2:
        sep = minima[1][0] / minima[0][0] if minima[0][0] > 0 else float("inf")
        print(f"  次点の局所最小 k={minima[1][1]:.4f} (コスト比 {sep:.2f}倍)")
        if sep < 1.3:
            print("  → 最良解が分離していない。データ不足か前提の誤りを疑うこと")

    assign(pts, k, args.tol)
    print(f"\n各ギヤの当てはまり（判定窓 ±{args.tol:.1f}%）")
    print("  速  理論比   予測比(k倍)  実測平均   n     偏差    ばらつき")
    for n in GEARS:
        sel = [p for p in pts if p["gear"] == n]
        pred = k * R[n]
        if not sel:
            print(f"  {n}   {R[n]:6.1f}   {pred:7.1f}      --       0      --       --")
            continue
        m = sum(p["ratio"] for p in sel) / len(sel)
        sd = (sum((p["ratio"] - m) ** 2 for p in sel) / len(sel)) ** 0.5
        print(f"  {n}   {R[n]:6.1f}   {pred:7.1f}   {m:7.1f} {len(sel):5d}  "
              f"{(m/pred-1)*100:+6.2f}%  ±{sd/m*100:.2f}%")

    nun = sum(1 for p in pts if p["gear"] is None)
    print(f"\n  窓の外（不確定） {nun} 点 / {len(pts)} = {nun/len(pts)*100:.1f}%")

    # 偏差がギヤ順に単調に流れていたら、単一 k で表せていない兆候。
    # ギヤ番号が上がるほど使用速度域が上がるので、速度計補正が非線形だと
    # 偏差が速度域と相関して片流れする。GPS が無くても検出できる。
    devs = []
    for n in GEARS:
        sel = [p for p in pts if p["gear"] == n]
        if len(sel) >= 5:
            m = sum(p["ratio"] for p in sel) / len(sel)
            devs.append((n, (m / (k * R[n]) - 1) * 100))
    if len(devs) >= 4:
        spread = max(d for _, d in devs) - min(d for _, d in devs)
        # ギヤ番号に対する偏差の回帰。厳密な単調性は隣接ギヤの微小な逆転で
        # 落ちるため、傾きと決定係数で傾向の強さを測る。
        xs = [n for n, _ in devs]
        ys = [d for _, d in devs]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
        sxx = sum((a - mx) ** 2 for a in xs)
        syy = sum((b - my) ** 2 for b in ys)
        slope = sxy / sxx if sxx else 0.0
        r2 = (sxy ** 2 / (sxx * syy)) if sxx and syy else 0.0
        print(f"  偏差の広がり {spread:.2f}%  傾き {slope:+.2f}%/段  R²={r2:.2f}")
        if spread > 2.0 and r2 > 0.7:
            print("  → ギヤ順に片流れしている。速度信号が非線形で、単一 k では"
                  "表せていない疑い")
        elif spread > 2.0:
            print("  → 広がりが大きいが傾向は無い。定常点の抽出条件を厳しくして再確認すること")

    hist(pts, k)
    linearity(pts)

    print("\n判定窓（この数値をアプリへ入れる）")
    print(f"  const GEAR_K = {k:.4f};")
    print(f"  const GEAR_TOL = {args.tol/100:.3f};")
    print("  const GEAR_R = {" + ", ".join(f"{n}:{R[n]:.1f}" for n in GEARS) + "};")


if __name__ == "__main__":
    main()
