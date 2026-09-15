"""BLE で OTA を有効にしてから、そのまま焼く。

基板の OTA は**既定で切、再起動で戻る**（LAN に無認証の書き込み口を開き続け
ないため）。開発中は毎回 BLE で `ota on` を打つことになるので、まとめた。
安全側の設計は変えていない —— 有効化は都度 BLE 経由で、再起動すれば閉じる。

    .venv/bin/python tools/klota.py
"""

import asyncio
import re
import subprocess
import sys

from bleak import BleakClient, BleakScanner

SVC = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"


async def enable_ota(timeout: float) -> str | None:
    dev = await BleakScanner.find_device_by_filter(
        lambda d, ad: SVC in [u.lower() for u in (ad.service_uuids or [])], timeout=timeout)
    if dev is None:
        print("基板が見つからない。12V が入っているか確認する")
        return None
    buf = []
    async with BleakClient(dev) as cli:
        await cli.start_notify(TX, lambda _, d: buf.append(d.decode("utf-8", "replace")))
        await asyncio.sleep(0.4)
        await cli.write_gatt_char(RX, b"ota on\n", response=False)
        # WiFi 接続に最大 25 秒かかる
        for _ in range(60):
            await asyncio.sleep(0.5)
            if "IP " in "".join(buf):
                break
    s = "".join(buf)
    m = re.search(r"IP (\d+\.\d+\.\d+\.\d+)", s)
    if not m:
        print("IP が返らない:"); print("  " + s.replace("\n", "\n  ")[-400:])
        return None
    print(s.strip().splitlines()[-2] if len(s.strip().splitlines()) > 1 else s.strip())
    return m.group(1)


def main() -> int:
    import functools; print = functools.partial(__builtins__.print, flush=True) if hasattr(__builtins__,"print") else globals()["print"]
    ip = asyncio.run(enable_ota(25.0))
    if not ip:
        return 1
    cmd = ["pio", "run", "-e", "explore_ota", "-t", "upload", "--upload-port", ip]
    print(f"\n$ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd="firmware")


if __name__ == "__main__":
    raise SystemExit(main())
