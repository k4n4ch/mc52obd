#!/usr/bin/env python3
"""CB250R (2018 / MC52) の OBD 対応 PID を停車状態で全数探索する。

やること:
  1. ELM327 を初期化し、ATDP で実際にロックしたプロトコルを記録
  2. サービス01 のサポート PID ビットマップ (0100/0120/.../01E0) を読む
  3. 申告された PID を実際に読んで値に変換
  4. --brute 指定時は 0x01-0xFF を総当たり（ビットマップ未申告の PID を探す）
  5. サービス03/07 (DTC)、サービス09 (VIN 等)、サービス22 の存在確認

結果は results/scan_<日時>.json と同 .md に保存する。

使い方:
    python tools/pidscan.py --list          # BLE デバイス一覧だけ出す
    python tools/pidscan.py                 # 通常スキャン
    python tools/pidscan.py --brute         # 未申告 PID も総当たり
    python tools/pidscan.py --addr <UUID>   # デバイス指定
"""

import argparse
import asyncio
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from elm327_ble import Elm327Ble, ElmError  # noqa: E402
from pids import PIDS, describe, expected_len  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"

ERRORS = (
    "NO DATA",
    "UNABLE TO CONNECT",
    "BUS INIT",
    "BUS ERROR",
    "CAN ERROR",
    "STOPPED",
    "ERROR",
    "?",
)


def is_error(lines):
    if not lines:
        return True
    return any(any(e in ln.upper() for e in ERRORS) for ln in lines)


async def send_retry(elm, cmd, log, retries=2, timeout=8.0, delay=0.15):
    """K-line は要求間隔が詰まると NO DATA を返すことがあるのでリトライする。

    生ログは同じコマンドを複数回叩いても上書きしないようキー名をずらして残す。
    """
    lines = []
    for attempt in range(retries + 1):
        lines = await elm.send(cmd, timeout=timeout)
        key = cmd if cmd not in log else f"{cmd}#{attempt + 1}"
        log[key] = lines
        if not is_error(lines):
            return lines
        await asyncio.sleep(delay * (attempt + 2))
    return lines


def parse_response(lines, mode, pid=None):
    """応答行から (header_hex, data_bytes) のリストを返す。

    ATH1 でヘッダが付くので、応答モードバイト (mode|0x40) と PID の並びを
    バイト境界で探して、そこから後ろをデータとみなす。
    """
    resp_mode = mode | 0x40
    out = []
    for ln in lines:
        hexstr = "".join(ln.split()).upper()
        if not hexstr or not all(c in "0123456789ABCDEF" for c in hexstr):
            continue
        if len(hexstr) % 2:
            hexstr = "0" + hexstr  # CAN の 11bit ヘッダ (例 "7E8") は 3 桁で出る
        b = bytes.fromhex(hexstr)
        idx = None
        for i in range(len(b) - (1 if pid is None else 1)):
            if b[i] != resp_mode:
                continue
            if pid is None or (i + 1 < len(b) and b[i + 1] == pid):
                idx = i
                break
        if idx is None:
            continue
        head = b[:idx].hex().upper()
        start = idx + (1 if pid is None else 2)
        data = b[start:]

        # ISO 14230 の形式バイト 0x8N は「モードバイト以降の長さ」を持つ。
        # ELM327 は末尾のチェックサムを落とさないので、ここで切り捨てる。
        lens = []
        if idx > 0 and (b[0] & 0xC0) == 0x80 and (b[0] & 0x3F):
            lens.append((b[0] & 0x3F) - (1 if pid is None else 2))
        if pid is not None and expected_len(pid):
            lens.append(expected_len(pid))
        lens = [n for n in lens if n > 0]
        if lens:
            n = min(lens)
            if len(data) >= n:
                data = data[:n]

        out.append((head, data))
    return out


async def read_supported(elm, log):
    """サポート PID ビットマップを辿り、申告された PID の集合を返す。"""
    supported = set()
    bitmaps = {}
    base = 0x00
    while base <= 0xE0:
        lines = await send_retry(elm, f"01{base:02X}", log, retries=3)
        parsed = parse_response(lines, 0x01, base) if not is_error(lines) else []
        if not parsed or len(parsed[0][1]) < 4:
            # このビットマップは読めなかった。連鎖ビットが分からないので
            # 打ち切らず次のベースへ進み、読めた分だけ拾う。
            bitmaps[f"{base:02X}"] = None
            base += 0x20
            continue
        _, data = parsed[0]
        bits = int.from_bytes(data[:4], "big")
        bitmaps[f"{base:02X}"] = f"{bits:08X}"
        for i in range(32):
            if bits & (1 << (31 - i)):
                supported.add(base + i + 1)
        if not (bits & 1):  # 最下位ビット = 次のビットマップの有無
            break
        base += 0x20
        await asyncio.sleep(0.1)
    return supported, bitmaps


async def read_pid(elm, pid, log, retries=2):
    lines = await send_retry(elm, f"01{pid:02X}", log, retries=retries)
    if is_error(lines):
        return None
    parsed = parse_response(lines, 0x01, pid)
    if not parsed:
        return None
    head, data = parsed[0]
    name, value, unit = describe(pid, data)
    return {
        "pid": f"{pid:02X}",
        "name": name,
        "raw": data.hex().upper(),
        "value": value,
        "unit": unit,
        "header": head,
        "responders": len(parsed),
    }


async def probe_other_services(elm, log):
    out = {}
    for cmd, key in (("03", "dtc_stored"), ("07", "dtc_pending"), ("0A", "dtc_permanent")):
        out[key] = await send_retry(elm, cmd, log, retries=2, timeout=10.0)
        await asyncio.sleep(0.1)

    lines = await send_retry(elm, "0900", log, retries=2, timeout=10.0)
    out["mode09_supported"] = lines
    if not is_error(lines):
        parsed = parse_response(lines, 0x09, 0x00)
        sub_supported = []
        if parsed and len(parsed[0][1]) >= 5:
            # 49 00 <count> <bitmap 4byte> の形なのでカウントバイトを飛ばす
            bits = int.from_bytes(parsed[0][1][1:5], "big")
            sub_supported = [i + 1 for i in range(32) if bits & (1 << (31 - i))]
        out["mode09_supported_pids"] = [f"{s:02X}" for s in sub_supported]
        for sub in sub_supported or [0x02, 0x04, 0x0A]:
            # マルチフレームは行数が多く時間がかかるのでタイムアウトを長めに
            out[f"mode09_{sub:02X}"] = await send_retry(
                elm, f"09{sub:02X}", log, retries=1, timeout=15.0
            )
            await asyncio.sleep(0.1)

    # サービス22 (メーカー固有 DID) が生きているかの当たりだけ取る。
    # NO DATA が期待値なのでリトライはしない。
    probes = {}
    for did in ("0000", "F190", "F1A0", "0100", "0101", "F810"):
        probes[did] = await send_retry(elm, f"22{did}", log, retries=0, timeout=8.0)
        await asyncio.sleep(0.1)
    out["mode22_probe"] = probes
    return out


def write_markdown(path, res):
    L = []
    L.append("# CB250R OBD スキャン結果\n")
    L.append(f"- 日時: {res['timestamp']}")
    L.append(f"- プロトコル: `{res['protocol']}` (ATDPN=`{res['protocol_num']}`)")
    L.append(f"- 申告 PID 数: {len(res['supported'])}")
    L.append(f"- 実応答 PID 数: {len(res['pids'])}\n")

    L.append("## サポート PID ビットマップ\n")
    L.append("| ベース | ビットマップ |")
    L.append("|---|---|")
    for k, v in res["bitmaps"].items():
        L.append(f"| `01{k}` | `{v}` |")
    L.append("")

    L.append("## 応答した PID\n")
    L.append("| PID | 名称 | 生データ | 値 | 単位 |")
    L.append("|---|---|---|---|---|")
    for p in res["pids"]:
        val = "" if p["value"] is None else p["value"]
        L.append(
            f"| `{p['pid']}` | {p['name']} | `{p['raw']}` | {val} | {p['unit']} |"
        )
    L.append("")

    undeclared = res.get("undeclared", [])
    if undeclared:
        L.append("## ビットマップ未申告だが応答した PID\n")
        L.append("| PID | 名称 | 生データ |")
        L.append("|---|---|---|")
        for p in undeclared:
            L.append(f"| `{p['pid']}` | {p['name']} | `{p['raw']}` |")
        L.append("")

    no_resp = res.get("declared_no_response", [])
    if no_resp:
        L.append(
            "## 申告されたが応答しなかった PID\n\n"
            + ", ".join(f"`{p}`" for p in no_resp)
            + "\n"
        )

    L.append("## その他サービス\n")
    L.append("```")
    L.append(json.dumps(res["services"], ensure_ascii=False, indent=2))
    L.append("```")
    path.write_text("\n".join(L), encoding="utf-8")


async def run(args):
    if args.list:
        devs = await Elm327Ble.discover()
        for addr, name in devs:
            print(f"{addr}  {name}")
        return 0

    elm = Elm327Ble(address=args.addr, name_hint=args.name, verbose=args.verbose)
    log = {}
    print("[*] BLE 接続中...")
    addr = await elm.connect()
    print(f"[+] 接続: {addr}")

    try:
        print("[*] ELM327 初期化 / プロトコル探索...")
        init = await elm.init(headers=True, timeout_ms=args.st)
        log.update(init["log"])
        print(f"[+] プロトコル: {init['protocol']} (ATDPN={init['protocol_num']})")

        print("[*] サポート PID ビットマップ取得...")
        await asyncio.sleep(0.3)  # バスイニット直後は間隔を空ける
        supported, bitmaps = await read_supported(elm, log)
        print(f"[+] 申告 PID: {len(supported)} 個 -> {sorted(f'{p:02X}' for p in supported)}")

        targets = sorted(supported)
        if args.brute:
            targets = list(range(0x01, 0x100))
            print("[*] 総当たりモード: 0x01-0xFF")

        pids, undeclared, missing = [], [], []
        for pid in targets:
            if pid % 0x20 == 0:
                continue  # ビットマップ用 PID は取得済み
            # 申告済みは NO DATA を疑ってリトライ、未申告は期待値が NO DATA なので即断
            r = await read_pid(elm, pid, log, retries=2 if pid in supported else 0)
            await asyncio.sleep(args.delay)
            if r is None:
                if pid in supported:
                    missing.append(f"{pid:02X}")
                continue
            if pid in supported:
                pids.append(r)
                v = "" if r["value"] is None else f"{r['value']} {r['unit']}"
                print(f"    {r['pid']} {r['name'][:38]:<38} {r['raw']:<10} {v}")
            else:
                undeclared.append(r)
                print(f"  ! {r['pid']} 未申告だが応答 {r['raw']}  ({r['name']})")

        print("[*] DTC / サービス09 / サービス22 確認...")
        services = await probe_other_services(elm, log)

        res = {
            "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
            "vehicle": "Honda CB250R 2018 (MC52)",
            "device": addr,
            "protocol": init["protocol"],
            "protocol_num": init["protocol_num"],
            "bitmaps": bitmaps,
            "supported": sorted(f"{p:02X}" for p in supported),
            "pids": pids,
            "undeclared": undeclared,
            "declared_no_response": missing,
            "services": services,
            "raw_log": log,
        }

        RESULTS.mkdir(exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
        jp = RESULTS / f"scan_{stamp}.json"
        mp = RESULTS / f"scan_{stamp}.md"
        jp.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        write_markdown(mp, res)
        print(f"\n[+] {jp}\n[+] {mp}")
        return 0
    finally:
        await elm.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="BLE デバイスを列挙して終了")
    ap.add_argument("--addr", help="BLE アドレス/UUID を直接指定")
    ap.add_argument("--name", help="デバイス名の部分一致で選ぶ")
    ap.add_argument("--brute", action="store_true", help="0x01-0xFF を総当たり")
    ap.add_argument("--delay", type=float, default=0.08, help="PID 間の待ち [s]")
    ap.add_argument("--st", type=int, default=None, help="ATST を ms 指定 (K-line 用)")
    ap.add_argument("-v", "--verbose", action="store_true")
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
