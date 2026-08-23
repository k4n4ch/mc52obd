#!/usr/bin/env python3
"""ELM327 対話ターミナル。1 行 1 コマンドで送って応答をそのまま出す。

スキャナで拾えなかった所を手で突くとき用。
    python tools/term.py
    > ATZ
    > ATDP
    > 010C
非対話でも使える:
    python tools/term.py -c ATZ -c ATSP0 -c 0100 -c ATDP
"""

import argparse
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from elm327_ble import Elm327Ble, ElmError  # noqa: E402


async def run(args):
    elm = Elm327Ble(address=args.addr, name_hint=args.name, verbose=False)
    addr = await elm.connect()
    print(f"[+] 接続: {addr}")
    try:
        if args.cmd:
            for c in args.cmd:
                lines = await elm.send(c, timeout=args.timeout)
                print(f"> {c}")
                for ln in lines:
                    print(f"  {ln}")
            return 0
        print("空行または Ctrl-D で終了")
        loop = asyncio.get_running_loop()
        while True:
            try:
                cmd = await loop.run_in_executor(None, input, "> ")
            except EOFError:
                break
            cmd = cmd.strip()
            if not cmd:
                break
            try:
                for ln in await elm.send(cmd, timeout=args.timeout):
                    print(f"  {ln}")
            except ElmError as e:
                print(f"  [!] {e}")
        return 0
    finally:
        await elm.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--addr")
    ap.add_argument("--name")
    ap.add_argument("-c", "--cmd", action="append", help="送るコマンド（複数可）")
    ap.add_argument("--timeout", type=float, default=10.0)
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
