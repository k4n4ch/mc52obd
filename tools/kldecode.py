"""基板が記録した生フレームのログを読む。

**中身の解釈が確定していなくても、この層は今すぐ書ける。** レコードへの分解、
時刻の復元、テーブル番号の取り出し、チェックサムの検算までは形式で決まっていて、
バイトの意味には依存しない。

    ファイル先頭   "MC52" ver:u8  開始壁時計:u32(unix)
    レコード       type:u8  dt:u16(前レコードからの ms)  len:u8  data[len]
    type           0x01 独自層の応答 / 0x02 標準層の応答 / 0x03 要求 / 0x10 メモ

使い方:
    python3 tools/kldecode.py private/logs/20260918_101530.bin          # 一覧
    python3 tools/kldecode.py x.bin --csv out.csv                       # CSV へ
    python3 tools/kldecode.py x.bin --table D1                          # 特定テーブルだけ
"""

import argparse
import csv
import datetime as dt
UTC = dt.timezone.utc
import struct
import sys

T_NAME = {0x01: "独自層", 0x02: "標準層", 0x03: "要求", 0x10: "メモ"}


def cs_two_complement(b: bytes) -> bool:
    """独自層のチェックサム＝総和の 2 の補数。全バイトの総和が 0 になる。"""
    return len(b) >= 2 and sum(b) % 256 == 0


def cs_iso14230(b: bytes) -> bool:
    """標準層は単純和。末尾が先行バイトの総和と一致する。"""
    return len(b) >= 2 and sum(b[:-1]) % 256 == b[-1]


def records(path):
    d = open(path, "rb").read()
    if d[:4] != b"MC52":
        raise SystemExit(f"{path}: 先頭が MC52 でない")
    ver = d[4]
    t0 = struct.unpack("<I", d[5:9])[0]
    i, ms = 9, 0
    while i + 4 <= len(d):
        typ, dtm, ln = d[i], struct.unpack("<H", d[i + 1:i + 3])[0], d[i + 3]
        i += 4
        if i + ln > len(d):
            print(f"  ★ 末尾が切れている（{len(d) - i} バイト残）", file=sys.stderr)
            break
        payload = d[i:i + ln]
        i += ln
        ms += dtm
        yield ver, t0, ms, typ, payload


def table_of(p: bytes):
    """独自層は `.. .. 71 TT ..`、要求は `72 05 71 TT CS`。TT を返す。"""
    if len(p) >= 4 and p[2] == 0x71:
        return p[3]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="生フレームのログを読む")
    ap.add_argument("path")
    ap.add_argument("--csv", help="CSV に書き出す")
    ap.add_argument("--table", help="このテーブル（16 進）だけ")
    ap.add_argument("--type", help="この type（16 進）だけ")
    a = ap.parse_args()

    want_t = int(a.table, 16) if a.table else None
    want_y = int(a.type, 16) if a.type else None

    rows, stat, bad = [], {}, 0
    t0 = ver = None
    for ver, t0, ms, typ, p in records(a.path):
        tb = table_of(p)
        if want_t is not None and tb != want_t:
            continue
        if want_y is not None and typ != want_y:
            continue
        ok = cs_two_complement(p) if typ in (0x01, 0x03) else \
             cs_iso14230(p) if typ == 0x02 else None
        if ok is False:
            bad += 1
        key = (typ, tb)
        stat[key] = stat.get(key, 0) + 1
        rows.append({
            "t_sec": f"{ms / 1000:.3f}",
            "iso_time": dt.datetime.fromtimestamp(t0 + ms / 1000, UTC).isoformat(timespec="milliseconds"),
            "type": T_NAME.get(typ, f"0x{typ:02X}"),
            "table": "" if tb is None else f"{tb:02X}",
            "len": len(p),
            "cs": "" if ok is None else ("ok" if ok else "NG"),
            "hex": p.hex(" ").upper(),
        })

    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else
                               ["t_sec", "iso_time", "type", "table", "len", "cs", "hex"])
            w.writeheader(); w.writerows(rows)
        print(f"{len(rows)} レコードを {a.csv} へ")
    else:
        for r in rows[:40]:
            print(f"  {r['t_sec']:>9}s {r['type']:<6} {r['table']:>2} "
                  f"[{r['len']:>2}] {r['cs']:<2} {r['hex'][:60]}")
        if len(rows) > 40:
            print(f"  … 他 {len(rows) - 40} レコード")

    print(f"\n形式 v{ver}  開始 {dt.datetime.fromtimestamp(t0, UTC).isoformat()}"
          f"  全 {len(rows)} レコード  チェックサム不一致 {bad}")
    print("type / テーブル別:")
    for (typ, tb), n in sorted(stat.items(), key=lambda x: -x[1]):
        print(f"  {T_NAME.get(typ, hex(typ)):<6} {'--' if tb is None else f'{tb:02X}':>3}  {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
