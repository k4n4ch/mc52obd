"""独自層の信号マップを、手元のログ全部から生成する。

**手で書くと更新のたびに写し間違える。** バイトごとの素性（出現回数・取った値の種類・
範囲・既知量との相関）は全部ログから計算できるので、文書ごと生成する。
解釈（「これは RPM」）だけは人が決めるので、下の `KNOWN` に置いて版管理する。

    python3 tools/klmap.py                      # 標準出力
    python3 tools/klmap.py -o docs/signal-map.md

読み方の要点は 3 つ。

    種類 1        定数。その系に信号が来ていない
    種類 2〜4     旗。状態を表す
    種類が多い    量。相関を見る

相関は Spearman（順位相関）。**同じフレームに入っている量（`0x11` 内の rpm・車速）とは
厳密に、別テーブルの量とは ±400ms で最も近いサンプルを当てる。** 別テーブルとの相関は
`poll` に両方を入れた区間しか計算できないので、被覆率も併記する。
"""

import argparse
import collections
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kldecode import records, table_of          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(ROOT, "private", "logs", "*.bin")

# ── 人が決めた解釈 ────────────────────────────────────────
# (テーブル, index) -> (名前, 根拠)。**測定で裏が取れたものだけ書く。**
KNOWN = {
    (0x11, 0): ("フレーム先頭 0x02", "全応答で固定"),
    (0x11, 1): ("総バイト数 0x19", "実長と一致"),
    (0x11, 2): ("コマンド 0x71", "要求の写し"),
    (0x11, 3): ("テーブル番号", "要求の写し"),
    (0x11, 4): ("**RPM 上位**", "アイドル 1428 / 空吹かし 3907 / 走行 6628"),
    (0x11, 5): ("**RPM 下位**", "同上"),
    (0x11, 6): ("**絶対スロットル `A×100/255`**",
                "標準層 `11` と同じ符号化。**アイドル 10.2% / 最小 9.8% が両者一致**"),
    (0x11, 7): ("**相対スロットル `A×100/255`**",
                "標準層 `45` 相当。全閉で 0。`[6]` と違い学習ゼロ点から測る。"
                "`[7] = 0.770×[6] − 20.08` が全開まで成り立つ（`[6]`=224 で 154、外挿 152.4）"),
    (0x11, 8): ("**水温センサの電圧コード**",
                "`[9]` はこれを表で引いた値（29→101℃、30→100、31→99、32→97。98℃ は現れない）"),
    (0x11, 9): ("**水温 −40℃**", "始動直後 44℃ / 暖機で上昇"),
    (0x11, 10): ("IAT 電圧?", "先行事例の配置。[11] と対"),
    (0x11, 11): ("**吸気温 −40℃**", "28℃ = 外気と一致"),
    (0x11, 12): ("MAP 電圧?", "先行事例の配置。[13] と対"),
    (0x11, 13): ("**吸気管圧力 kPa**", "アイドルで 30〜97 を往復。単気筒の脈動。標準層 0B と同挙動"),
    (0x11, 14): ("未使用 0xFF", "全サンプル FF"),
    (0x11, 15): ("未使用 0xFF", "全サンプル FF"),
    (0x11, 16): ("**電圧 ×0.1V**", "発電中 14.5V / 停止 12V 台"),
    (0x11, 17): ("**車速 km/h**",
                 "標準層 0D と同じ信号（切り捨て）。(`[17]`+0.5)/GPS は 20〜109km/h で "
                 "0.943〜0.954、速度に依存しない（2 走行）"),
    (0x11, 18): ("**噴射時間 上位**",
                 "LSB 1/256 ms。アイドル 611〜648 / 全閉で 0 = 燃料カット / レブリミッタでも 0。"
                 "全開 9,139rpm で 2,143（8.37ms）が 1 回転 6.57ms を超える → **1 サイクル 1 噴射**"),
    (0x11, 19): ("**噴射時間 下位**", "同上。endian は BE"),
    (0x11, 20): ("**点火進角 `A/2 − 64`**",
                 "標準層 `0E` と同じ符号化。**アイドルで両者 9.5° が一致**。"
                 "アイドル 9.5° → 5500rpm 59°、`FF` で天井"),
    (0x11, 21): ("暖機で減る量（粗）", "暖機後は水温に従う（34℃ 58 → 99℃ 47）。**`[22-23]` の 1/128 相当**"),
    (0x11, 22): ("同（16bit 上位）",
                 "`[22-23]` で 6338〜12404。**水温だけの関数ではない** —— 始動後は水温一定のまま"
                 "時間で減る（23℃ で 12,404 → 20 秒で約 8,500、冷間始動 2 回で再現）"),
    (0x11, 23): ("同（16bit 下位）", "単体では 42% が不変で飛ぶが、`[22]` と対で見ると滑らか"),
    (0xD1, 0): ("フレーム先頭 0x02", "全応答で固定"),
    (0xD1, 1): ("総バイト数 0x0B", "実長と一致"),
    (0xD1, 2): ("コマンド 0x71", "要求の写し"),
    (0xD1, 3): ("テーブル番号", "要求の写し"),
    (0xD1, 4): ("**駆動が繋がっているか**",
                "00 駆動 / 01 N かクラッチ / 03 スタンド。状態 A〜D ＋ 実走 2 本で確定"),
    (0xD1, 8): ("**エンジン状態（ビットフィールド）**",
                "bit0 運転（クランキングで噴射と同時に立つ）/ bit1 常時 0 / **bit2 ≒ スロットルが開いている**"
                "（`[6] ≥ 29`、全閉 26、93.4%）/ **bit3 ≒ スロットル開＋走行中**"
                "（`[6] ≥ 29` かつ車速 ≥ 20、94.9%）。いずれも推定"),
    (0xD1, 9): ("**ラジエータファン**",
                "水温コード `0x11[8]` が 29 以下で入（101℃）、32 以上で切（97℃）。ヒステリシス 2 目盛り。"
                "8 bit の値で理解できる。1 回の作動は 11.6〜17.2 秒"),
    (0xD1, 5): ("未同定",
                "全フレームで 00。10,773rpm・全開・水温 20℃ の冷間始動・100km/h を含めても 00。"
                "動く事象に出会っていない可能性は残る"),
    (0xD1, 6): ("未同定", "同上"),
    (0xD1, 7): ("未同定", "同上"),
    (0x00, 0): ("フレーム先頭 0x02", ""), (0x00, 1): ("総バイト数 0x0F", ""),
    (0x00, 2): ("コマンド 0x71", ""), (0x00, 3): ("テーブル番号", ""),
    (0x20, 0): ("フレーム先頭 0x02", ""), (0x20, 1): ("総バイト数 0x08", ""),
    (0x20, 2): ("コマンド 0x71", ""), (0x20, 3): ("テーブル番号", ""),
    (0x20, 4): ("**O2 センサ電圧 ×0.02V**（推定）",
                "燃料カットで 0、暖機後アイドル 43〜44（= 0.86V、標準層 `14` のアイドル 0.86V と一致）、"
                "巡航で 4〜45 を往復。活性前は C1/C2 固定"),
    (0x20, 5): ("**O2 フィードバック補正**（推定、`0x80` が 0）",
                "アイドル・燃料カット・全開・活性前は 0x80 固定、巡航だけ 106〜122。"
                "標準層 `03` のクローズドループ区間と重なる。スケール未確定"),
    (0x20, 6): ("**フィードバック許可**（推定）",
                "走行ごとに 1 回だけ 0→1。冷間始動では水温 37℃（2 回）、温間始動では始動 7.6 秒後。"
                "以後は燃料カット・全開でも落ちない"),
    (0x61, 0): ("フレーム先頭 0x02", ""), (0x61, 1): ("総バイト数 0x19", ""),
    (0x61, 2): ("コマンド 0x71", ""), (0x61, 3): ("テーブル番号", ""),
    (0x70, 0): ("フレーム先頭 0x02", ""), (0x70, 1): ("総バイト数 0x08", ""),
    (0x70, 2): ("コマンド 0x71", ""), (0x70, 3): ("テーブル番号", ""),
    (0xD0, 0): ("フレーム先頭 0x02", ""), (0xD0, 1): ("総バイト数 0x1A", ""),
    (0xD0, 2): ("コマンド 0x71", ""), (0xD0, 3): ("テーブル番号", ""),
    (0xD0, 15): ("負荷系の量（16bit 上位）",
                 "`[15-16]` はスロットル・噴射と r = 0.87〜0.91（2 走行）。閉 485〜490、全開約 1,950。正体は未同定"),
    (0xD0, 16): ("同（16bit 下位）", ""),
}
# 最終バイトはチェックサム
TAIL = "チェックサム（総和の 2 の補数）"

NOTE = {
    0x00: "keep-alive に使われているテーブル。停車の全区間で固定だった",
    0x11: "**センサ群。本命。** 先行事例（CRF250L）の配置がそのまま当たった。\n\n"
          "先行事例に記載が無かった `[20]`〜`[23]` も同定した。**`[20]` は点火進角**で、"
          "標準層 `0E` と同じ符号化（アイドルで両者 9.5°）。**`[21]` と `[22-23]` は同じ量の"
          "粗／細**で、暖機で減る。始動直後は水温一定のまま時間で減るので、水温だけの関数では"
          "ない（始動後増量の減衰と読める）。**スケールは未確定**（アイドル回転数と同じ向きに動く: "
          "`[21]`=58 で 1542rpm、47 で 1412rpm）。\n\n"
          "スロットルも標準層と同じ符号化で 2 系統あった —— **`[6]` が絶対（PID `11` 相当）、"
          "`[7]` が相対（PID `45` 相当）**。`[6]` はアイドル 10.2% / 最小 9.8% が標準層の実測と"
          "小数第 1 位まで一致した",
    0x20: "8 バイト。**O2 フィードバック系と推定。** `[4]` O2 電圧、`[5]` 補正量、`[6]` 許可。"
          "燃料カット・全開・アイドル・冷間の 4 条件で振る舞いが揃う（2026-09-24、3 走行）",
    0x61: "**凍結データ。** 25 分・暖機の進行をまたいでバイト同一。水温 20〜26℃ の冷間起動を含む "
          "10 回の起動でも同一。`0x11` と同じ 25 バイト長だが配置は当てはまらない",
    0x70: "8 バイト。全サンプル固定",
    0xD0: "26 バイト。ほぼ 0 だが `[15-16]`・`[17]`・`[24]` が動く。`[15-16]` は負荷系。"
          "`[17]`・`[24]` は既知量との相関が弱く未同定",
    0xD1: "**駆動とエンジンの状態。** index 4 が比推定に欠けていた入力",
}


def rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def spearman(a, b):
    if len(a) < 30:
        return None
    ra, rb = rank(a), rank(b)
    n = len(ra)
    ma, mb = sum(ra) / n, sum(rb) / n
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((x - mb) ** 2 for x in rb)
    if va == 0 or vb == 0:
        return None
    cov = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n))
    return cov / (va * vb) ** 0.5


def collect(paths):
    """テーブル -> [(絶対時刻, payload)] と、参照量の時系列を作る。"""
    frames = collections.defaultdict(list)
    for path in paths:
        try:
            rows = list(records(path))
        except SystemExit:
            continue
        if not rows:
            continue
        t0 = rows[0][1]
        for _, _, ms, typ, p in rows:
            if typ != 0x01:
                continue
            t = table_of(p)
            if t is not None:
                frames[t].append((t0 + ms / 1000, bytes(p)))
    for t in frames:
        frames[t].sort()
    return frames


def nearest(series, t, tol=0.4):
    import bisect
    ks = series[0]
    i = bisect.bisect(ks, t)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(ks) and (best is None or abs(ks[j] - t) < abs(ks[best] - t)):
            best = j
    if best is None or abs(ks[best] - t) > tol:
        return None
    return series[1][best]


def main():
    ap = argparse.ArgumentParser(description="独自層の信号マップを生成する")
    ap.add_argument("-o", "--out", help="書き出し先（省略すると標準出力）")
    ap.add_argument("logs", nargs="*", help="対象ログ（省略すると private/logs/*.bin）")
    a = ap.parse_args()
    paths = a.logs or sorted(glob.glob(LOGS))
    frames = collect(paths)
    if not frames:
        raise SystemExit("ログが無い")

    # 参照量: 0x11 の rpm と車速（同一フレーム）、0xD1 の index4
    t11 = [f for f in frames.get(0x11, []) if len(f[1]) >= 25]
    rpm_s = ([t for t, _ in t11], [(p[4] << 8) | p[5] for _, p in t11])
    spd_s = ([t for t, _ in t11], [p[17] for _, p in t11])

    out = []
    w = out.append
    w("# 独自層の信号マップ（MC52 / CB250R 2018）\n")
    w("**`tools/klmap.py` が `private/logs/*.bin` から生成する。手で編集しない。**")
    w("解釈（名前と根拠）はスクリプト内の `KNOWN` に置いてあり、そこだけが人の判断。\n")
    w("測定の経緯と根拠は [`FINDINGS.md`](FINDINGS.md)、プロトコルの仕様は")
    w("[`../firmware/SPEC.md`](../firmware/SPEC.md)。\n")
    w("## 読み方\n")
    w("| 種類 | 意味 |")
    w("|---|---|")
    w("| 1 | **定数。** その系に信号が来ていない |")
    w("| 2〜4 | **旗。** 状態を表す |")
    w("| 多い | **量。** 相関を見る |\n")
    w("相関は Spearman（順位相関）。`0x11` 内の rpm・車速は同一フレームなので厳密、")
    w("別テーブルとの相関は ±400ms で最も近いサンプルを当てたもの（被覆率を併記）。\n")
    w("## 材料\n")
    w("| ログ | 独自層の応答 |")
    w("|---|---|")
    for path in paths:
        try:
            rows = list(records(path))
        except SystemExit:
            continue
        c = collections.Counter(table_of(p) for _, _, _, typ, p in rows
                                if typ == 0x01 and table_of(p) is not None)
        if not c:
            continue
        top = " ".join(f"`{k:02X}`×{v}" for k, v in sorted(c.items()) if v > 5)
        w(f"| `{os.path.basename(path)}` | {top or '（走査のみ）'} |")
    w("")

    for tid in sorted(frames):
        fr = [f for f in frames[tid] if len(f[1]) > 5]
        if len(fr) < 5:
            continue
        lens = collections.Counter(len(p) for _, p in fr)
        n = min(lens)
        w(f"## テーブル `{tid:02X}`\n")
        w(f"{NOTE.get(tid, '')}\n")
        w(f"サンプル **{len(fr)}**　長さ {'/'.join(str(x) for x in sorted(lens))} バイト\n")
        w("| index | 種類 | 範囲 | 値 | rpm 相関 | 車速 相関 | 解釈 | 根拠 |")
        w("|---:|---:|---|---|---:|---:|---|---|")
        for i in range(n):
            vals = [p[i] for _, p in fr]
            st = sorted(set(vals))
            rng = f"`{min(st):02X}`" if len(st) == 1 else f"`{min(st):02X}`〜`{max(st):02X}`"
            shown = " ".join(f"`{v:02X}`" for v in st) if len(st) <= 4 else ""
            cr = cs = ""
            if len(st) >= 5:
                if tid == 0x11:
                    xa = [(p[4] << 8) | p[5] for _, p in fr]
                    xb = [p[17] for _, p in fr]
                    ya = vals
                else:
                    pair = [(nearest(rpm_s, t), nearest(spd_s, t), p[i]) for t, p in fr]
                    pair = [x for x in pair if x[0] is not None]
                    if len(pair) >= 30:
                        xa = [x[0] for x in pair]; xb = [x[1] for x in pair]; ya = [x[2] for x in pair]
                    else:
                        xa = xb = ya = []
                if ya:
                    ra, rb = spearman(xa, ya), spearman(xb, ya)
                    cov = "" if tid == 0x11 else f"（{len(ya)}）"
                    cr = f"{ra:+.2f}{cov}" if ra is not None else ""
                    cs = f"{rb:+.2f}" if rb is not None else ""
            name, why = KNOWN.get((tid, i), ("", ""))
            if i == n - 1 and not name:
                name, why = TAIL, "総和が 0 になる"
            if not name:
                name = "**未同定**" if len(st) > 1 else "定数"
            w(f"| {i} | {len(st)} | {rng} | {shown} | {cr} | {cs} | {name} | {why} |")
        w("")

    text = "\n".join(out) + "\n"
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"{a.out} に {len(out)} 行")
    else:
        print(text)


if __name__ == "__main__":
    main()
