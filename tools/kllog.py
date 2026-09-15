"""基板に記録した生フレームのログを BLE で吸い出す。

基板側（`firmware` の `explore`）は**生フレームをそのまま LittleFS へ追記**する。
テーブルのバイト配置も噴射時間の単位も未確定なので、解釈して書くと間違いが
確定した時点で過去のログが全部無価値になる。復号はこちら側でやる。

転送は notify のテキスト経路に base64 で流し、**CRC32 で検証する**。
実測 33KB/s に対し実効 25KB/s。

    .venv/bin/python tools/kllog.py ls
    .venv/bin/python tools/kllog.py get 20260918_101530.bin
    .venv/bin/python tools/kllog.py get --all
"""

import argparse
import asyncio
import base64
import binascii
import os
import re
import sys
import time

from bleak import BleakClient, BleakScanner

SVC_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
OUT_DIR = "private/logs"          # 位置情報を含みうるので既定は gitignore 配下


class Session:
    """行単位に組み直す。notify はバイト数で刻まれていて行の途中で切れる。"""

    def __init__(self):
        self.buf = ""
        self.lines: list[str] = []

    def feed(self, data: bytes):
        self.buf += data.decode("utf-8", "replace")
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.lines.append(line.rstrip("\r"))

    def take(self):
        out, self.lines = self.lines, []
        return out


async def connect():
    dev = await BleakScanner.find_device_by_filter(
        lambda d, ad: SVC_UUID in [u.lower() for u in (ad.service_uuids or [])], timeout=20)
    if dev is None:
        print("基板が見つからない。12V が入っているか確認する")
        return None, None
    ses = Session()
    cli = BleakClient(dev)
    await cli.connect()
    await cli.start_notify(TX_UUID, lambda _, d: ses.feed(d))
    await asyncio.sleep(0.4)
    return cli, ses


async def send(cli, text):
    payload = (text + "\n").encode()
    for i in range(0, len(payload), 180):
        await cli.write_gatt_char(RX_UUID, payload[i:i + 180], response=False)
        await asyncio.sleep(0.02)


async def collect(ses, until, timeout=600.0, quiet=3.0):
    """`until` にマッチする行が来るまで集める。無音が続いたら諦める。"""
    got, last = [], time.time()
    while time.time() - last < quiet and time.time() - last < timeout:
        await asyncio.sleep(0.05)
        new = ses.take()
        if new:
            last = time.time()
            got += new
            for ln in new:
                if until(ln):
                    return got
    return got


async def cmd_ls(cli, ses):
    await send(cli, "ls")
    for ln in await collect(ses, lambda l: "ファイル /" in l, quiet=2.0):
        print(ln)


async def fetch(cli, ses, name, out_dir):
    print(f"\n-- {name} --")
    await send(cli, f"get {name}")
    lines = await collect(ses, lambda l: l.startswith("END "), timeout=900, quiet=8.0)

    try:
        bi = next(i for i, l in enumerate(lines) if l.startswith("BEGIN "))
        ei = next(i for i, l in enumerate(lines) if l.startswith("END "))
    except StopIteration:
        print("  ★ 転送が完了しなかった")
        return False
    # **サイズは末尾から取る。** 名前に空白が入りうるので固定位置では壊れる
    size = int(lines[bi].split()[-1])
    want = int(lines[ei].split()[-1], 16)
    blob = base64.b64decode("".join(lines[bi + 1:ei]))
    got = binascii.crc32(blob) & 0xFFFFFFFF

    ok = (got == want) and (len(blob) == size)
    print(f"  {len(blob)} / {size} バイト   CRC {got:08X} / {want:08X}   "
          + ("**一致**" if ok else "★ 不一致"))
    if not ok:
        return False
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, os.path.basename(name))
    with open(path, "wb") as f:
        f.write(blob)
    print(f"  保存 {path}")
    return True


async def run(args) -> int:
    cli, ses = await connect()
    if cli is None:
        return 1
    try:
        if args.cmd == "ls":
            await cmd_ls(cli, ses)
        elif args.cmd == "get":
            names = args.names
            if args.all:
                await send(cli, "ls")
                lines = await collect(ses, lambda l: "ファイル /" in l, quiet=2.0)
                names = [m.group(1) for l in lines
                         if (m := re.match(r"\s+(\S+\.bin)\s", l))]
                print(f"{len(names)} ファイル: {names}")
            if not names:
                print("名前が無い（--all か名前を指定する）"); return 1
            ng = [n for n in names if not await fetch(cli, ses, n, args.out)]
            if ng:
                print(f"\n★ 失敗 {ng}"); return 1
    finally:
        await cli.disconnect()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="基板の生フレームログを BLE で吸い出す")
    ap.add_argument("cmd", choices=["ls", "get"])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--all", action="store_true", help="全ファイルを取る")
    ap.add_argument("--out", default=OUT_DIR, help=f"保存先（既定 {OUT_DIR}）")
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
