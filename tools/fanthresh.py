"""ラジエータファンの入切しきい値を、水温コードの 1 目盛りより細かく推定し、見かけでないかを確かめる。

    python3 tools/fanthresh.py                 # private/logs の全セッション

**やること。** 入切 1 回ごとに、その前後の窓でコード（`0x11[8]`）の時系列へモデルを最尤で当てはめ、
切替時刻での値をコードの小数で読む。

    u(τ) = a + b·τ + c·τ²          τ = t − t_switch [s]。コード単位の連続値
    見えるコード k = floor(u + ε)、ε ~ N(0, σ²)
    P(k | u) = Φ((k+1−u)/σ) − Φ((k−u)/σ)

u の原点は「コード k の下端が k」（切り捨て）という約束で、しきい値 u* = a。

**見かけでないかの確かめ。** ノイズ σ がほぼ 0 の窓では、モデルが縛るのは「目盛りが変わった時刻」
だけになり、手順が推定値を目盛りの境目へ寄せている可能性がある。そこで切替時刻をわざと
−3 / −1.5 / +1.5 秒ずらして同じ推定をする。手順が健全なら、推定値は傾き×ずらし時間だけ境目から
離れ、ばらつきも増える。**実際の切替時刻でいちばんそろうこと**が、しきい値が本当にそこにある
ことの根拠になる。

scipy を使わない（正規分布の累積は math.erf、最適化は自前の Nelder–Mead）。
"""

import glob
import math
import os
import re
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kldecode import records, table_of          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(ROOT, "private", "logs")
WIN = {1: (-25.0, 2.0), 0: (-15.0, 2.0)}   # 入: 温まっていく 25 秒、切: ファンで冷える 15 秒
SHIFTS = (-3.0, -1.5, 0.0, 1.5)
SQ2 = math.sqrt(2)
_erf = np.vectorize(math.erf)


def sessions():
    """`名前_NN.bin` を 1 セッションに束ね、(コード系列, ファン系列) を返す。時刻は通算 ms。"""
    by = defaultdict(list)
    for p in sorted(glob.glob(os.path.join(LOGS, "*.bin"))):
        m = re.match(r"^(.*?)(?:_(\d{2}))?\.bin$", os.path.basename(p))
        by[m.group(1)].append(p)
    for name, paths in by.items():
        C, F, off = [], [], 0
        for p in sorted(paths):
            last = 0
            for _, _, ms, typ, pl in records(p):
                last = ms
                if typ != 0x01:
                    continue
                t = table_of(pl)
                if t == 0x11 and len(pl) >= 25:
                    C.append((off + ms, pl[8]))
                elif t == 0xD1 and len(pl) >= 11:
                    F.append((off + ms, pl[9]))
            off += last
        if C and any(f for _, f in F):
            yield name, np.array(C, float), F


def nll(p, t, k):
    a, b, c, ls = p
    s = math.exp(ls)
    u = a + b * t + c * t * t
    pr = 0.5 * (_erf((k + 1 - u) / (s * SQ2)) - _erf((k - u) / (s * SQ2)))
    return -np.log(np.clip(pr, 1e-12, 1)).sum()


def nelder_mead(f, x0, step, it=4000, tol=1e-9):
    pts = [np.array(x0, float)]
    for i in range(len(x0)):
        x = np.array(x0, float); x[i] += step[i]; pts.append(x)
    vals = [f(x) for x in pts]
    for _ in range(it):
        o = np.argsort(vals); pts = [pts[i] for i in o]; vals = [vals[i] for i in o]
        if abs(vals[-1] - vals[0]) < tol:
            break
        cen = np.mean(pts[:-1], axis=0)
        xr = cen + (cen - pts[-1]); fr = f(xr)
        if fr < vals[0]:
            xe = cen + 2 * (cen - pts[-1]); fe = f(xe)
            pts[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = xr, fr
        else:
            xc = cen + 0.5 * (pts[-1] - cen); fc = f(xc)
            if fc < vals[-1]:
                pts[-1], vals[-1] = xc, fc
            else:
                for i in range(1, len(pts)):
                    pts[i] = pts[0] + 0.5 * (pts[i] - pts[0]); vals[i] = f(pts[i])
    return pts[0], vals[0]


def fit(t, k, a0):
    best = None
    for b0 in (-0.2, -0.05, 0.05, 0.2):
        for ls0 in (math.log(0.15), math.log(0.4)):
            x, v = nelder_mead(lambda p: nll(p, t, k), [a0, b0, 0.0, ls0], [0.3, 0.05, 0.002, 0.5])
            if best is None or v < best[1]:
                best = (x, v)
    return best[0]


def estimate(data, to, shift):
    out = []
    for name, C, F in data:
        for i in range(1, len(F)):
            if F[i][1] == F[i - 1][1] or F[i][0] - F[i - 1][0] > 500 or F[i][1] != to:
                continue
            ts = (F[i][0] + F[i - 1][0]) / 2 / 1000 + shift     # 切替は直前の D1 との間。中点
            lo, hi = WIN[to]
            m = (C[:, 0] / 1000 >= ts + lo) & (C[:, 0] / 1000 <= ts + hi)
            t, k = C[m, 0] / 1000 - ts, C[m, 1]
            if len(t) < 40 or k.min() == k.max():
                continue
            out.append(fit(t, k, float(np.median(k[-10:])) + 0.5))
    return np.array(out)


def main():
    data = list(sessions())
    print("セッション:", " ".join(n for n, _, _ in data))
    print("\nずらし   入 u*（平均 / SD / 回数）     切 u*（平均 / SD / 回数）")
    for sh in SHIFTS:
        row = []
        for to in (1, 0):
            U = estimate(data, to, sh)
            row.append(f"{U[:, 0].mean():6.3f} / {U[:, 0].std(ddof=1):.3f} / {len(U):2d}")
        print(f"{sh:+5.1f}s   {row[0]}      {row[1]}")
    print("\nu はコード単位で、コード k の下端が k（入の境目 29/30 = 30、切の境目 31/32 = 32）")


if __name__ == "__main__":
    main()
