"""基板のログを、ビュワー（`map.html`）が食える CSV にする。

`kldecode.py` が出すのはレコードの生ダンプで、値の時系列ではない。こちらは
**`0x11` のフレーム 1 つを 1 行**にし、最も近い `0xD1` の駆動状態を添える。

**列名はビュワーの別名表に合わせてある**ので、出した CSV をそのまま放り込める。

    t_sec iso_time 0C_rpm 0D_speed 11_tps 45_tps_rel 05_ect 0F_iat 0B_map
    42_volt 0E_adv skew_ms drive i8 inj  [lat lon speed_gps gps_acc alt]

**`skew_ms` は 0 を出す。** ビュワーは rpm と車速の取得時刻ずれを補間で直すが、
独自層は同一フレームなのでずれが無い（ELM327 は PID ごとに別リクエストで
加速 +7.3% / 減速 −5.8% の誤差が出る）。0 を渡せば補正が働かない。

**パートは名前順に連結する。** 1 本 256KB で切り替わるので 1 走行が複数ファイルに
なる。`dt` の連鎖はまたいでも切れていないので、そのまま足せば隙間なく繋がる。
**各パートのヘッダ壁時計は最大 5 秒遅れる**ので時刻の基準には使わず、最初のパートの
ヘッダか `note t=<epoch>` のアンカーから取る。

使い方:

    python3 tools/klcsv.py private/logs/r260919_1224.bin -o out.csv
    python3 tools/klcsv.py private/logs/auto0007_*.bin -o out.csv \
        --gps private/logs/gps_2026-09-19T0250.csv        # 地図を出すなら
"""

import argparse
import bisect
import csv
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kldecode import records, table_of, wallclock_anchor   # noqa: E402

UTC = dt.timezone.utc
COLS = ["t_sec", "iso_time", "0C_rpm", "0D_speed", "11_tps", "45_tps_rel",
        "05_ect", "0F_iat", "0B_map", "42_volt", "0E_adv", "skew_ms",
        "drive", "i8", "inj"]
GPS_COLS = ["lat", "lon", "speed_gps", "gps_acc", "alt"]


def merge_parts(paths):
    """パートを名前順に連結し、(通算ms, type, payload) の列と時刻の基準を返す。"""
    out, base_epoch, off = [], None, 0.0
    for i, path in enumerate(sorted(paths)):
        rows = list(records(path))
        if not rows:
            continue
        hdr = rows[0][1]
        if i == 0 and hdr >= 1700000000:
            base_epoch = hdr            # 先頭パートのヘッダが使えるならそれ
        last = 0
        for _, _, ms, typ, p in rows:
            out.append((off + ms, typ, p))
            last = ms
        a = wallclock_anchor(path)      # 自動記録はヘッダが未設定。アンカーで取り直す
        if a and base_epoch is None:
            base_epoch = a[1] - (off + a[0]) / 1000
        off += last
    return out, base_epoch


def load_gps(path):
    g = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        try:
            g.append((int(r["epoch_ms"]) / 1000,
                      float(r["lat"]), float(r["lon"]),
                      float(r["speed_mps"]) * 3.6 if r.get("speed_mps") else None,
                      float(r["acc_m"]) if r.get("acc_m") else None,
                      float(r["alt_m"]) if r.get("alt_m") else None))
        except (KeyError, TypeError, ValueError):
            continue
    g.sort()
    return g


def gps_at(g, keys, t):
    """**緯度経度と速度は線形補間する。** 1Hz の測位に対し行は 5Hz なので、最近傍だと
    地図が階段になる。精度は最近傍のまま（補間する量ではない）。"""
    i = bisect.bisect(keys, t)
    if i == 0 or i >= len(keys):
        return None
    a, b = g[i - 1], g[i]
    if b[0] - a[0] > 3:
        return None
    w = (t - a[0]) / (b[0] - a[0])
    def lerp(x, y):
        return None if (x is None or y is None) else x + (y - x) * w
    near = a if w < 0.5 else b
    return {"lat": lerp(a[1], b[1]), "lon": lerp(a[2], b[2]),
            "speed_gps": lerp(a[3], b[3]), "gps_acc": near[4],
            "alt": lerp(a[5], b[5])}


def main() -> int:
    ap = argparse.ArgumentParser(description="基板のログをビュワー用 CSV にする")
    ap.add_argument("logs", nargs="+", help="ログ（パートは名前順に連結）")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--gps", help="スマホの測位 CSV（絶対時刻で突合して地図を出す）")
    a = ap.parse_args()

    recs, base = merge_parts(a.logs)
    if not recs:
        raise SystemExit("レコードが無い")
    if base is None:
        print("★ 絶対時刻が無い（ヘッダ未設定でアンカーも無し）。iso_time は空にする",
              file=sys.stderr)
    g = keys = None
    if a.gps:
        g = load_gps(a.gps)
        keys = [x[0] for x in g]
        print(f"測位 {len(g)} 点を読んだ")

    cols = COLS + (GPS_COLS if g else [])
    drive = i8 = None
    n = 0
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, cols)
        w.writeheader()
        for ms, typ, p in recs:
            if typ != 0x01:
                continue
            t = table_of(p)
            if t == 0xD1 and len(p) >= 11:
                drive, i8 = p[4], p[8]
                continue
            if t != 0x11 or len(p) < 25:
                continue
            row = {
                "t_sec": round(ms / 1000, 3),
                "iso_time": (dt.datetime.fromtimestamp(base + ms / 1000, UTC)
                             .isoformat(timespec="milliseconds").replace("+00:00", "Z")
                             if base else ""),
                "0C_rpm": (p[4] << 8) | p[5],
                "0D_speed": p[17],
                "11_tps": round(p[6] * 100 / 255, 2),      # 絶対スロットル
                "45_tps_rel": round(p[7] * 100 / 255, 2),  # 相対スロットル
                "05_ect": p[9] - 40,
                "0F_iat": p[11] - 40,
                "0B_map": p[13],
                "42_volt": round(p[16] / 10, 1),
                "0E_adv": round(p[20] / 2 - 64, 1),        # 標準層 0E と同じ符号化
                "skew_ms": 0,                              # 同一フレーム。ずれが無い
                "drive": "" if drive is None else drive,
                "i8": "" if i8 is None else i8,
                "inj": (p[18] << 8) | p[19],
            }
            if g:
                row.update({k: "" for k in GPS_COLS})
                p2 = gps_at(g, keys, base + ms / 1000) if base else None
                if p2:
                    row.update({k: ("" if p2[k] is None else round(p2[k], 7))
                                for k in GPS_COLS})
            w.writerow(row)
            n += 1
    span = recs[-1][0] / 1000
    print(f"{n} 行 / {span / 60:.1f} 分 / {len(a.logs)} パート → {a.out}")
    if base:
        print(f"  開始 {dt.datetime.fromtimestamp(base)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
