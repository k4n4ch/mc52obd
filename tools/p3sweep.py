#!/usr/bin/env python3
"""要求前の待ち時間を掃引して、行の脱落（NO DATA）が最小になる設定を探す。

**停車＋アイドリングで測れる。** 走行は要らない。実走ログの解析で、脱落率が
回転数帯・車速帯を通じて平坦（停車中も 38%）だったため、停車での測定に
代表性がある。

仮説は ISO 14230 の P3min（応答終了から次の要求までの最小間隔、約 55ms）を
割っていること。アプリはレスポンス駆動で '>' の直後に撃つので、待たずに
撃つと ECU に無視され、ELM327 が ST タイムアウトして NO DATA を返す。

    python tools/p3sweep.py --addr <UUID>
    python tools/p3sweep.py --addr <UUID> --delays 0,30,55,80 --cycles 30
    python tools/p3sweep.py --addr <UUID> --st 14,28,3c        # ATST も振る
"""

import argparse
import asyncio
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from elm327_ble import Elm327Ble, ElmError  # noqa: E402
from pidscan import is_error, parse_response  # noqa: E402

# アプリと同じ順序。速い層 3 個 ＋ 遅い層 1 個で 1 周期
FAST = [0x0C, 0x0D, 0x11]
SLOW = [0x04, 0x42, 0x05, 0x03]


async def measure(elm, delay_ms, cycles):
    """1 周期 4 要求を cycles 回。PID ごとの成否と所要時間を返す。"""
    ok = {}
    ng = {}
    t0 = time.monotonic()
    for c in range(cycles):
        seq = FAST + [SLOW[c % len(SLOW)]]
        for pid in seq:
            if delay_ms:
                await asyncio.sleep(delay_ms / 1000)
            try:
                lines = await elm.send(f"01{pid:02X}", timeout=5.0)
            except ElmError:
                lines = []
            good = bool(lines) and not is_error(lines) and parse_response(lines, 0x01, pid)
            (ok if good else ng)[pid] = (ok if good else ng).get(pid, 0) + 1
    dur = time.monotonic() - t0
    return ok, ng, dur


async def run(args):
    elm = Elm327Ble(address=args.addr, name_hint=args.name)
    print("[*] BLE 接続中...")
    addr = await elm.connect()
    print(f"[+] 接続: {addr}")
    try:
        init = await elm.init(headers=True, protocol="5")
        print(f"[+] プロトコル: {init['protocol']}\n")

        delays = [int(x) for x in args.delays.split(",")]
        sts = [int(x, 16) for x in args.st.split(",")]
        pids = FAST + SLOW

        print(f"1 周期 = {len(FAST)}(速) + 1(遅) 要求 × {args.cycles} 周期")
        print(f"{'ATST':>6} {'待ち':>6} {'欠測':>7} {'周期':>8} {'実効':>8}   PID 別欠測率")
        best = None
        for st in sts:
            await elm.send("ATAT0")
            await elm.send(f"ATST{st:02X}")
            await asyncio.sleep(0.3)
            for d in delays:
                ok, ng, dur = await measure(elm, d, args.cycles)
                tot = sum(ok.values()) + sum(ng.values())
                miss = sum(ng.values())
                rate = miss / tot * 100 if tot else 0
                per = "  ".join(
                    f"{p:02X}:{ng.get(p,0)*100//max(1,ok.get(p,0)+ng.get(p,0)):3d}%"
                    for p in pids)
                cyc = dur / args.cycles
                print(f"{st*4:5d}ms {d:5d}ms {rate:6.1f}% {cyc*1000:7.0f}ms "
                      f"{1/cyc:6.2f}Hz   {per}")
                # 記録レート = 周期あたり 1 行、ただし 0x0C が落ちた周期は書けない
                eff = (1 / cyc) * (1 - ng.get(0x0C, 0) / max(1, ok.get(0x0C, 0) + ng.get(0x0C, 0)))
                if best is None or eff > best[0]:
                    best = (eff, st, d, rate)
        print(f"\n[+] 記録レート最良: ATST {best[1]*4}ms / 待ち {best[2]}ms "
              f"→ {best[0]:.2f} Hz（欠測 {best[3]:.1f}%）")
        print("    アプリ側は localStorage の mc52_p3 に待ち時間[ms]を入れる")
        return 0
    finally:
        await elm.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--addr")
    ap.add_argument("--name")
    ap.add_argument("--delays", default="0,20,40,55,70,90,120", help="要求前の待ち [ms]")
    ap.add_argument("--st", default="14", help="ATST の値 (hex, 4ms 単位, カンマ区切り)")
    ap.add_argument("--cycles", type=int, default=30, help="設定あたりの周期数")
    args = ap.parse_args()
    try:
        sys.exit(asyncio.run(run(args)))
    except ElmError as e:
        print(f"[!] {e}", file=sys.stderr); sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
