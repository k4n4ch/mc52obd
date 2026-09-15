"""独自層のテーブルを実時間で監視し、**動いたバイトを見つける**ための計器。

ファーム側の `poll` が生バイトを機械可読な行で押し出すので、こちらはそれを
並べて**どのバイトが動いたか**を出す。解釈は一切しない。

    P <経過ms> <TT> <hex..>

**なぜスナップショットでは足りないか。** `d` や `m` は 1 回読むだけなので、
「クラッチを握った瞬間にどのバイトが変わるか」が取れない。バイトの同定は
操作と変化の対応でしか進まないので、時系列と操作の記録が同時に要る。

画面に出るのは 3 つだけ。

    現在値      生の hex。動いたバイトを強調する
    種類        そのバイトが取った異なる値の数。**1 なら定数、2 なら旗、多いなら量**
    直近        スパークライン。操作と見比べる

使い方（既定は 0xD1 と 0x11 を 200ms 周期）:

    .venv/bin/python tools/klwatch.py
    .venv/bin/python tools/klwatch.py --tables D1 11 10 --ms 300 --rec probe

画面の下の行はそのまま基板へ渡る。`note クラッチ握った` と打てばログに目印が
入り、後から `kldecode.py` で突き合わせられる。`q` だけで終了。
"""

import argparse
import asyncio
import codecs
import collections
import sys
import termios
import time
import tty

from bleak import BleakClient, BleakScanner

SVC_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

HIST = 32                      # スパークラインに使う直近サンプル数
BLOCKS = "▁▂▃▄▅▆▇█"
MSG_LINES = 6                  # P 以外の出力を出す行数


class Table:
    """1 テーブルぶんのバイト毎の統計。"""

    def __init__(self, tid):
        self.tid = tid
        self.cur = b""
        self.n = 0
        self.miss = 0
        self.seen = collections.defaultdict(set)              # idx -> 値の集合
        self.hist = collections.defaultdict(lambda: collections.deque(maxlen=HIST))

    def feed(self, data):
        if data is None:
            self.miss += 1
            return
        self.cur = data
        self.n += 1
        for i, v in enumerate(data):
            self.seen[i].add(v)
            self.hist[i].append(v)

    def movers(self):
        """動いたバイトを、種類の多い順に返す。"""
        m = [(i, len(s)) for i, s in self.seen.items() if len(s) > 1]
        m.sort(key=lambda t: (-t[1], t[0]))
        return m


def spark(vals):
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return BLOCKS[0] * len(vals)
    return "".join(BLOCKS[int((v - lo) / (hi - lo) * (len(BLOCKS) - 1))] for v in vals)


class Screen:
    def __init__(self, color=True):
        self.color = color
        self.msgs = collections.deque(maxlen=MSG_LINES)
        self.dec = codecs.getincrementaldecoder("utf-8")("replace")
        self.buf = ""            # P 行以外の受信テキスト
        self.input = ""
        self.tables = {}
        self.order = []          # ファームが押し出す順（sorted では poll の順と食い違う）
        self.t0 = time.monotonic()
        self.cycles = 0
        self.last_ms = 0

    # ── 受信 ────────────────────────────────────────────────
    def feed(self, data: bytes):
        self.buf += self.dec.decode(data)
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.line(line.rstrip("\r"))

    def line(self, s):
        if not s.startswith("P "):
            if s.strip():
                self.msgs.append(s)
            return
        f = s.split()
        if len(f) < 3:
            return
        try:
            ms, tid = int(f[1]), int(f[2], 16)
        except ValueError:
            return
        if tid not in self.tables:
            self.tables[tid] = Table(tid)
            self.order.append(tid)
        t = self.tables[tid]
        if f[3:] == ["-"]:
            t.feed(None)
        else:
            try:
                t.feed(bytes(int(x, 16) for x in f[3:]))
            except ValueError:
                return
        self.last_ms = ms
        # **最初に現れたテーブルで周期を数える。** ファームは poll の順に押し出し、
        # 無応答でも P 行を出すので、これが欠けることはない
        if tid == self.order[0]:
            self.cycles += 1

    # ── 描画 ────────────────────────────────────────────────
    def c(self, s, code):
        return f"\033[{code}m{s}\033[0m" if self.color else s

    def render(self):
        el = time.monotonic() - self.t0
        hz = self.cycles / el if el > 0.5 else 0.0
        o = ["\033[H"]

        def put(s=""):
            o.append(s + "\033[K\r\n")     # 消去だけでは行が進まない

        put(self.c(f" MC52 klwatch   {el:6.1f}s   {self.cycles} 周期   {hz:.2f} Hz"
                   f"   テーブル {' '.join(f'{t:02X}' for t in self.order)}", "7"))
        put()
        for tid in self.order:
            t = self.tables[tid]
            put(self.c(f"{tid:02X}", "1;36") +
                f"  長さ {len(t.cur):3d}  応答 {t.n}  欠 {t.miss}")
            mv = dict(t.movers())
            for off in range(0, len(t.cur), 16):
                row = [f"  {off:3d} "]
                for i in range(off, min(off + 16, len(t.cur))):
                    h = f"{t.cur[i]:02X}"
                    row.append(" " + (self.c(h, "1;33") if i in mv else h))
                put("".join(row))
            if not mv:
                put(self.c("       まだ動いたバイトが無い", "2"))
            for i, k in t.movers()[:12]:
                h = t.hist[i]
                put(f"   [{i:3d}] {t.cur[i]:02X}  種類 {k:3d}  "
                    f"{min(t.seen[i]):02X}-{max(t.seen[i]):02X}  {spark(h)}")
            put()
        put(self.c(" 出力", "2"))
        for m in list(self.msgs)[-MSG_LINES:]:
            put("  " + m[:110])
        for _ in range(MSG_LINES - len(self.msgs)):
            put()
        put()
        put("> " + self.input)
        o.append("\033[J")
        sys.stdout.write("".join(o))
        sys.stdout.flush()


async def run(a) -> int:
    print(f"サービス {SVC_UUID[:8]}… を探す（{a.timeout:.0f} 秒）…")
    # 名前ではなくサービス UUID で探す（macOS の名前キャッシュを避ける。klconsole.py と同じ）
    dev = await BleakScanner.find_device_by_filter(
        lambda d, ad: SVC_UUID.lower() in [u.lower() for u in (ad.service_uuids or [])],
        timeout=a.timeout)
    if dev is None:
        print("見つからない。基板に 12V が入っているか確認する")
        return 1

    sc = Screen(color=not a.no_color)
    async with BleakClient(dev) as cli:
        print(f"接続: {dev.address}  MTU={getattr(cli, 'mtu_size', '?')}")
        await cli.start_notify(TX_UUID, lambda _, d: sc.feed(d))

        async def send(text):
            p = (text + "\n").encode()
            for i in range(0, len(p), 180):
                await cli.write_gatt_char(RX_UUID, p[i:i + 180], response=False)
                await asyncio.sleep(0.02)

        await asyncio.sleep(0.5)
        await send(f"time {int(time.time())}")        # 基板に RTC が無い
        await asyncio.sleep(0.3)
        if a.init:
            await send("w")
            await asyncio.sleep(2.5)
        if a.rec:
            await send(f"rec on {a.rec}")
            await asyncio.sleep(0.4)
        await send(f"poll {' '.join(a.tables)} {a.ms}")

        loop = asyncio.get_running_loop()
        # **端末でない場合もある**（記録を取るだけの自動実行）。その時は入力を諦めて
        # 描画だけ回す。termios を非 TTY に当てると例外で落ちる
        tty_ok = sys.stdin.isatty()
        fd = sys.stdin.fileno() if tty_ok else -1
        old = termios.tcgetattr(fd) if tty_ok else None
        quit_ev = asyncio.Event()
        outq = asyncio.Queue()

        # **端末を自前で持つ。** 全画面を毎回描き直すので、readline に任せると
        # 入力中の文字が消える。1 文字ずつ受けて入力行も自分で描く。
        def on_key():
            for ch in sys.stdin.read(1):
                if ch in "\r\n":
                    line, sc.input = sc.input.strip(), ""
                    if line in ("q", "!q"):
                        quit_ev.set()
                    elif line:
                        outq.put_nowait(line)
                        sc.msgs.append(f"> {line}")
                elif ch == "\x7f":
                    sc.input = sc.input[:-1]
                elif ch == "\x03":
                    quit_ev.set()
                elif ch.isprintable():
                    sc.input += ch

        try:
            if tty_ok:
                tty.setcbreak(fd)
                loop.add_reader(fd, on_key)
            sys.stdout.write("\033[2J")
            deadline = time.monotonic() + a.sec if a.sec else None
            while not quit_ev.is_set():
                if deadline and time.monotonic() > deadline:
                    break
                while not outq.empty():
                    await send(outq.get_nowait())
                sc.render()
                try:
                    await asyncio.wait_for(quit_ev.wait(), timeout=1.0 / a.fps)
                except asyncio.TimeoutError:
                    pass
        finally:
            if tty_ok:
                loop.remove_reader(fd)
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()
            # **止めてから抜ける。** 放っておくと基板は流し続ける
            await send("poll off")
            await asyncio.sleep(0.4)
            if a.rec:
                await send("rec off")
                await asyncio.sleep(0.8)

        for tid in sc.order:
            t = sc.tables[tid]
            print(f"{tid:02X}  応答 {t.n}  欠 {t.miss}  "
                  f"動いたバイト {' '.join(f'[{i}]x{k}' for i, k in t.movers())}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="独自層テーブルの実時間監視（動いたバイトを探す）")
    ap.add_argument("--tables", nargs="+", default=["D1", "11"], help="16 進 2 桁")
    ap.add_argument("--ms", type=int, default=200, help="poll の周期 [ms]")
    ap.add_argument("--rec", help="同時に基板側の記録を開始する（名前）")
    ap.add_argument("--init", action="store_true", help="先に w（独自層の初期化）を打つ")
    ap.add_argument("--fps", type=float, default=5.0, help="描き直しの回数 [/s]")
    ap.add_argument("--sec", type=float, help="この秒数で自動終了（既定は q まで）")
    ap.add_argument("-t", "--timeout", type=float, default=20.0, help="スキャンの秒数")
    ap.add_argument("--no-color", action="store_true")
    a = ap.parse_args()
    try:
        return asyncio.run(run(a))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
