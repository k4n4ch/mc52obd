"""探索ファーム（firmware の explore）を BLE 越しに叩く対話コンソール。

**バイクの横でノート PC を J3 に繋がずに済ませるための道具。** 基板は
`MC52-explore` として広告していて、Nordic UART 相当の write / notify 一対で
コマンドと出力をやり取りする。

接続すると**壁時計を自動で送り込む**。基板に RTC が無いので、これをやらないと
記録した時刻をスマホの GPS ログと突き合わせられない。

使い方:
    .venv/bin/python tools/klconsole.py

    > ?              コマンド一覧（基板側が返す）
    > w              独自層の初期化
    > s              テーブル総当たり
    > X 72 05 71 D1  チェックサムを付けて送る
    > brk 70         K 線を 70ms Low に落とす
    > !log out.txt   以降の出力をファイルにも落とす（こちら側の機能）
    > !q             抜ける

`!` で始まるものだけこちら側で処理し、それ以外は素通しで基板へ送る。
**基板側のコマンドを増やしてもこのスクリプトを直す必要は無い。**
"""

import argparse
import asyncio
import sys
import time

from bleak import BleakClient, BleakScanner

DEV_NAME = "MC52-explore"
SVC_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # こちら → 基板
TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # 基板 → こちら


class Console:
    def __init__(self, logfile=None):
        self.log = None
        if logfile:
            self.open_log(logfile)

    def open_log(self, path):
        if self.log:
            self.log.close()
        self.log = open(path, "a", encoding="utf-8")
        self.log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
        print(f"[記録先 {path}]")

    def feed(self, data: bytes):
        s = data.decode("utf-8", "replace")
        sys.stdout.write(s)
        sys.stdout.flush()
        if self.log:
            self.log.write(s)
            self.log.flush()


async def run(timeout: float, logfile: str | None) -> int:
    print(f"{DEV_NAME} を探す（{timeout:.0f} 秒）…")
    dev = await BleakScanner.find_device_by_name(DEV_NAME, timeout=timeout)
    if dev is None:
        print("見つからない。基板に 12V が入っているか確認する")
        return 1

    con = Console(logfile)
    async with BleakClient(dev) as cli:
        print(f"接続: {dev.address}  MTU={getattr(cli, 'mtu_size', '?')}")
        await cli.start_notify(TX_UUID, lambda _, d: con.feed(d))

        async def send(text: str):
            payload = (text + "\n").encode()
            # 1 回の write が MTU を超えないよう刻む
            for i in range(0, len(payload), 180):
                await cli.write_gatt_char(RX_UUID, payload[i:i + 180], response=False)
                await asyncio.sleep(0.02)

        # **接続したら壁時計を送る。** 基板に RTC が無く、これをやらないと
        # 記録を GPS ログと突き合わせられない。
        await asyncio.sleep(0.5)
        await send(f"time {int(time.time())}")
        await asyncio.sleep(0.5)

        loop = asyncio.get_running_loop()
        print("接続完了。? で一覧、!q で終了\n")
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            line = line.rstrip("\n")
            if line in ("!q", "!quit"):
                break
            if line.startswith("!log "):
                con.open_log(line[5:].strip())
                continue
            if not line:
                continue
            await send(line)
            await asyncio.sleep(0.1)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="explore ファームを BLE 越しに叩く対話コンソール")
    ap.add_argument("-t", "--timeout", type=float, default=20.0, help="スキャンの秒数")
    ap.add_argument("-l", "--log", help="出力を落とすファイル")
    a = ap.parse_args()
    return asyncio.run(run(a.timeout, a.log))


if __name__ == "__main__":
    raise SystemExit(main())
