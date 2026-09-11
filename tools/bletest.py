"""selftest ファームの BLE スループットを Mac 側で受ける。

`firmware` の `selftest` 環境（`b` コマンド）が `MC52-selftest` として広告し、
notify でデータを流し続ける。こちらはそれを 1 本の接続で受けて**実効レートを
測る**。基板側の表示とこちら側の実測が食い違ったら、詰まっているのは基板では
なく macOS 側の接続パラメータということになる。

確かめたいのは HANDOFF.md の見積もり。

    既定（MTU 23・1M PHY）        1〜2KB/s   1 時間ぶんの転送に 12〜25 分＝実用外
    MTU 247 ＋ 2M PHY で         20〜50KB/s  30 秒〜1 分

記録は 1 時間あたりバイナリ 0.32MB（`HANDOFF.md`「Track B の構成」）なので、
実測レートからその転送に何秒かかるかまで出す。

**macOS は MTU も PHY もアプリから指定できない。** CoreBluetooth が勝手に
決めるので、こちらは結果を観測するだけ。`bleak` が返す `mtu_size` は
CoreBluetooth の "maximum write value length" 由来で、notify のペイロード上限
とは一致しないことがある。**判断はレートの実測値で行う。**

使い方:
    python3 tools/bletest.py            # 10 秒測る
    python3 tools/bletest.py -d 30      # 30 秒測る
"""

import argparse
import asyncio
import time

from bleak import BleakClient, BleakScanner

DEV_NAME = "MC52-selftest"
SVC_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

LOG_MB_PER_HOUR = 0.32          # HANDOFF.md「Track B の構成」


async def run(duration: float, timeout: float) -> int:
    print(f"{DEV_NAME} を探す（{timeout:.0f} 秒）…")
    dev = await BleakScanner.find_device_by_name(DEV_NAME, timeout=timeout)
    if dev is None:
        print("見つからない。基板側で 'b' を押して広告を開始しているか確認する")
        return 1

    print(f"見つかった: {dev.address}")
    async with BleakClient(dev) as cli:
        try:
            print(f"接続。MTU = {cli.mtu_size}（CoreBluetooth が決める。参考値）")
        except Exception:
            print("接続。MTU は取得できない")

        total = 0
        packets = 0
        sizes: set[int] = set()
        first: float | None = None
        last = 0.0

        def on_notify(_, data: bytearray) -> None:
            nonlocal total, packets, first, last
            if first is None:
                first = time.perf_counter()
            total += len(data)
            packets += 1
            sizes.add(len(data))
            last = time.perf_counter()

        await cli.start_notify(TX_UUID, on_notify)
        print(f"{duration:.0f} 秒受ける…")
        await asyncio.sleep(duration)
        await cli.stop_notify(TX_UUID)

        if not packets or first is None:
            print("1 バイトも来ない。基板側が notify を出しているか確認する")
            return 1

        # 最初の通知から最後までで測る。接続直後の待ちを含めない
        span = max(last - first, 1e-6)
        rate = total / span
        print()
        print(f"  受信      {total} バイト / {packets} パケット / {span:.2f} 秒")
        print(f"  パケット長 {sorted(sizes)}")
        print(f"  実効レート **{rate / 1024:.1f} KB/s**")

        need = LOG_MB_PER_HOUR * 1024 * 1024 / rate
        print(f"  記録 1 時間ぶん（{LOG_MB_PER_HOUR}MB）の転送に {need:.0f} 秒")
        print()
        if rate / 1024 < 5:
            print("  ★ 既定のまま（MTU 23・1M PHY）の水準。設計どおり実用外")
        elif rate / 1024 < 20:
            print("  ★ 中間。MTU は広がったが 2M PHY が効いていない可能性がある")
        else:
            print("  見積もり（20〜50KB/s）の水準に達している")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="selftest ファームの BLE スループットを受けて実効レートを測る")
    ap.add_argument("-d", "--duration", type=float, default=10.0, help="測定する秒数")
    ap.add_argument("-t", "--timeout", type=float, default=20.0, help="スキャンの秒数")
    a = ap.parse_args()
    return asyncio.run(run(a.duration, a.timeout))


if __name__ == "__main__":
    raise SystemExit(main())
