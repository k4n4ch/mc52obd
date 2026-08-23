#!/usr/bin/env python3
"""対応 PID を連続ポーリングして CSV に落とす。

K-Line は 1 要求あたり数十 ms かかるため、ポーリングする PID を絞るほど
サンプリング周期が上がる。実測した周期は終了時に表示する。

CSV には換算値と、再解釈できるよう生バイト列の両方を残す。

    python tools/logger.py --addr <UUID> --sec 150
    python tools/logger.py --addr <UUID> --sec 60 --pids 0C,0B,11,04
"""

import argparse
import asyncio
import csv
import datetime as dt
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from elm327_ble import Elm327Ble, ElmError  # noqa: E402
from pidscan import is_error, parse_response  # noqa: E402
from pids import PIDS, describe  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"

# K-Line + BLE ELM327 の総リクエスト予算は実測で約 6.3 Hz（158ms/req）しかない。
# 全 PID を毎周期回すと 0.45 Hz まで落ちて過渡が捉えられないため、速い信号だけを
# 毎周期、遅い信号は 1 周期に 1 個ずつ持ち回りで読む。
FAST_PIDS = "0C,11,0B"          # 回転数・スロットル・吸気管圧力
SLOW_PIDS = "0E,14,04,05,0F,03,06,07,42,0D,45"

SHORT = {
    0x03: "fuelsys", 0x04: "load", 0x05: "ect", 0x06: "stft", 0x07: "ltft",
    0x0B: "map", 0x0C: "rpm", 0x0D: "speed", 0x0E: "adv", 0x0F: "iat",
    0x11: "tps", 0x14: "o2", 0x42: "volt", 0x45: "tps_rel",
}


def _parse(s):
    return [int(p, 16) for p in s.split(",") if p.strip()]


async def run(args):
    fast = _parse(args.fast)
    slow = _parse(args.slow)
    pids = fast + slow
    elm = Elm327Ble(address=args.addr, name_hint=args.name)
    print("[*] BLE 接続中...")
    addr = await elm.connect()
    print(f"[+] 接続: {addr}")

    try:
        print("[*] 初期化...")
        init = await elm.init(headers=True)
        print(f"[+] プロトコル: {init['protocol']}")
        # 応答待ちを詰めて 306ms/req → 158ms/req。欠測が増えるようなら ATST を伸ばす
        await elm.send("ATAT0")
        await elm.send(f"ATST{args.st:02X}")
        await asyncio.sleep(0.3)

        RESULTS.mkdir(exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
        path = RESULTS / f"log_{stamp}.csv"

        cols = ["t_sec", "iso_time"]
        for p in pids:
            cols.append(f"{p:02X}_{SHORT.get(p, 'x')}")
        cols.append("raw")

        t0 = time.monotonic()
        n = 0
        miss = 0
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            while time.monotonic() - t0 < args.sec:
                # 速い信号は毎周期、遅い信号は 1 周期に 1 個ずつ持ち回り
                this_cycle = list(fast)
                if slow:
                    this_cycle.append(slow[n % len(slow)])

                vals, raws = {}, []
                for p in this_cycle:
                    try:
                        lines = await elm.send(f"01{p:02X}", timeout=5.0)
                    except ElmError:
                        raws.append(f"{p:02X}=ERR")
                        miss += 1
                        continue
                    if is_error(lines):
                        raws.append(f"{p:02X}=ND")
                        miss += 1
                        continue
                    parsed = parse_response(lines, 0x01, p)
                    if not parsed:
                        raws.append(f"{p:02X}=?")
                        miss += 1
                        continue
                    _, data = parsed[0]
                    _, value, _ = describe(p, data)
                    # 換算式が無い項目（ビットマップ等）は生 hex を値欄に入れる
                    vals[p] = data.hex().upper() if value is None else value
                    raws.append(f"{p:02X}={data.hex().upper()}")

                # 未サンプルの列は空欄。解析側で必要なら前値保持すればよい
                row_vals = [vals.get(p, "") for p in pids]
                t = round(time.monotonic() - t0, 3)
                w.writerow(
                    [t, dt.datetime.now().isoformat(timespec="milliseconds")]
                    + row_vals
                    + [";".join(raws)]
                )
                fh.flush()
                n += 1
                if n % 20 == 0:
                    print(f"  t={t:6.1f}s n={n:4d} rpm={vals.get(0x0C,'?')} "
                          f"tps={vals.get(0x11,'?')} map={vals.get(0x0B,'?')}",
                          flush=True)

        dur = time.monotonic() - t0
        print(f"\n[+] {n} サンプル / {dur:.1f}s = {n / dur:.2f} Hz "
              f"(速 {len(fast)} + 遅 1 PID/周期、欠測 {miss})")
        print(f"[+] {path}")
        return 0
    finally:
        await elm.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--addr")
    ap.add_argument("--name")
    ap.add_argument("--sec", type=float, default=120.0, help="記録時間 [s]")
    ap.add_argument("--fast", default=FAST_PIDS, help="毎周期読む PID (hex, カンマ区切り)")
    ap.add_argument("--slow", default=SLOW_PIDS, help="持ち回りで読む PID")
    ap.add_argument("--st", type=lambda x: int(x, 16), default=0x14,
                    help="ATST の値 (hex, 4ms 単位。既定 14=80ms)")
    args = ap.parse_args()
    try:
        sys.exit(asyncio.run(run(args)))
    except ElmError as e:
        print(f"[!] {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
