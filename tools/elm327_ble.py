"""ELM327 BLE トランスポート (macOS / CoreBluetooth を bleak 経由で叩く)。

ELM327 の BLE ドングルは Classic SPP ではないので /dev/cu.* が生えない。
GATT の write / notify キャラクタリスティックで行単位のテキストをやり取りする。

サービス UUID は fl4obd (k4n4ch) の Web Bluetooth 実装と同じ 2 種を試す:
  Type A: 0000fff0-... (FFF0/FFF1/FFF2)
  Type B: e7810a71-... (iOS 向けドングルに多い)
どちらも見つからない場合は、notify と write を持つキャラクタリスティックを
全サービスから総当たりで探す。
"""

import asyncio
import re

from bleak import BleakClient, BleakScanner

SVC_UUIDS = [
    "0000fff0-0000-1000-8000-00805f9b34fb",
    "e7810a71-73ae-499d-8c15-faa9aef0c3f2",
]

NAME_HINTS = (
    "obd",
    "elm",
    "vgate",
    "veepeak",
    "viecar",
    "konnwei",
    "icar",
    "vlink",
    "v-link",
    "mini",
)

PROMPT = ">"
CHUNK = 20  # BLE 既定 MTU での write ペイロード上限


class ElmError(Exception):
    pass


class Elm327Ble:
    def __init__(self, address=None, name_hint=None, verbose=False):
        self.address = address
        self.name_hint = name_hint
        self.verbose = verbose
        self.client = None
        self.write_char = None
        self.notify_char = None
        self._buf = ""
        self._evt = asyncio.Event()

    # ── 探索・接続 ────────────────────────────────────────────
    @staticmethod
    async def discover(timeout=8.0):
        """周辺の BLE デバイスを列挙し (address, name) のリストを返す。"""
        devs = await BleakScanner.discover(timeout=timeout)
        return [(d.address, d.name or "") for d in devs]

    async def _pick_device(self):
        if self.address:
            return self.address
        hint = (self.name_hint or "").lower()
        found = await BleakScanner.discover(timeout=8.0)
        for d in found:
            name = (d.name or "").lower()
            if hint:
                if hint in name:
                    return d.address
            elif any(h in name for h in NAME_HINTS):
                return d.address
        names = ", ".join(f"{d.name or '?'}({d.address})" for d in found) or "(なし)"
        raise ElmError(f"ELM327 らしき BLE デバイスが見つからない。検出: {names}")

    def _on_rx(self, _sender, data: bytearray):
        self._buf += data.decode("ascii", errors="replace")
        if PROMPT in self._buf:
            self._evt.set()

    async def _bind_chars(self):
        svcs = {s.uuid.lower(): s for s in self.client.services}

        def pick(chars):
            notify = write = None
            for c in chars:
                p = c.properties
                if ("notify" in p or "indicate" in p) and notify is None:
                    notify = c
                if ("write" in p or "write-without-response" in p) and write is None:
                    write = c
            return notify, write

        for uuid in SVC_UUIDS:
            svc = svcs.get(uuid)
            if not svc:
                continue
            notify, write = pick(svc.characteristics)
            if notify or write:
                self.notify_char = notify or write
                self.write_char = write or notify
                return uuid

        # フォールバック: 全サービス総当たり
        for svc in self.client.services:
            notify, write = pick(svc.characteristics)
            if notify and write:
                self.notify_char, self.write_char = notify, write
                return svc.uuid

        raise ElmError("notify/write を持つキャラクタリスティックが見つからない")

    async def connect(self):
        addr = await self._pick_device()
        self.client = BleakClient(addr)
        await self.client.connect()
        uuid = await self._bind_chars()
        await self.client.start_notify(self.notify_char, self._on_rx)
        if self.verbose:
            print(f"[ble] connected {addr} svc={uuid[4:8]}")
        return addr

    async def close(self):
        if self.client and self.client.is_connected:
            try:
                await self.client.stop_notify(self.notify_char)
            except Exception:
                pass
            await self.client.disconnect()

    # ── 送受信 ────────────────────────────────────────────────
    async def send(self, cmd, timeout=10.0, drain=False):
        """コマンドを 1 行送り、'>' プロンプトまでの応答行リストを返す。

        コマンドエコーと 'SEARCHING...' は除去する。
        """
        if not self.client or not self.client.is_connected:
            raise ElmError("未接続")

        self._buf = ""
        self._evt.clear()
        payload = (cmd + "\r").encode("ascii")
        no_resp = "write-without-response" in self.write_char.properties
        for i in range(0, len(payload), CHUNK):
            await self.client.write_gatt_char(
                self.write_char, payload[i : i + CHUNK], response=not no_resp
            )

        try:
            await asyncio.wait_for(self._evt.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            if not self._buf:
                raise ElmError(f"応答なし: {cmd}")
            # プロンプトは来なかったが部分応答はある
        else:
            # マルチフレーム応答は最終行がプロンプトと同じ通知に乗らないことが
            # あるため、少し待って取りこぼしを回収する。1 行応答では純粋な
            # オーバーヘッドになるので、必要な呼び出しだけ drain=True にする。
            if drain:
                prev = len(self._buf)
                await asyncio.sleep(0.08)
                while len(self._buf) != prev:
                    prev = len(self._buf)
                    await asyncio.sleep(0.08)

        raw = self._buf.replace(PROMPT, "")
        lines = [ln.strip() for ln in re.split(r"[\r\n]+", raw)]
        out = []
        for ln in lines:
            if not ln:
                continue
            if ln.upper() == cmd.upper().replace(" ", "") or ln.upper() == cmd.upper():
                continue  # エコー
            if ln.upper().startswith("SEARCHING"):
                continue
            out.append(ln)
        if self.verbose:
            print(f"[elm] {cmd:<8} -> {out}")
        return out

    async def init(self, headers=True, timeout_ms=None, protocol="0"):
        """ELM327 を既定状態へ。実際にロックしたプロトコル名を返す。

        K-line (ISO 9141-2 / ISO 14230-4) は応答が遅いので、必要なら
        timeout_ms で ATST を伸ばす (4ms 単位、最大 1020ms)。
        """
        log = {}
        for cmd in ("ATZ", "ATE0", "ATL0", "ATS0", "ATAT1"):
            log[cmd] = await self.send(cmd, timeout=8.0)
            await asyncio.sleep(0.1)
        log["ATH1" if headers else "ATH0"] = await self.send(
            "ATH1" if headers else "ATH0"
        )
        if timeout_ms:
            st = max(1, min(255, round(timeout_ms / 4)))
            log[f"ATST{st:02X}"] = await self.send(f"ATST{st:02X}")
        log[f"ATSP{protocol}"] = await self.send(f"ATSP{protocol}")

        # 最初の実リクエストでプロトコル自動探索が走る
        log["0100"] = await self.send("0100", timeout=20.0)
        dp = await self.send("ATDP", timeout=8.0)
        dpn = await self.send("ATDPN", timeout=8.0)
        log["ATDP"], log["ATDPN"] = dp, dpn
        return {
            "protocol": dp[0] if dp else "?",
            "protocol_num": dpn[0] if dpn else "?",
            "log": log,
        }
