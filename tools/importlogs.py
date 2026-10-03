#!/usr/bin/env python3
"""スマホから降ろした走行ログを `private/logs/` へ取り込む。

ブラウザのダウンロード先に溜まったログを `private/logs/` へ集める。CSV と
同名の GPX は対で扱う。`private/` 直下は位置情報を含むデータ全般の置き場で、
走行ログはその下の `logs/` に分けている。

    python3 tools/importlogs.py              # 取り込む（元は残す）
    python3 tools/importlogs.py --move       # 一致を確認してから元を消す
    python3 tools/importlogs.py --list       # private/logs/ の中身を一覧する
    python3 tools/importlogs.py --from DIR   # 取り込み元を指定する

**同名で中身が違うファイルは決して上書きしない。** 走行ログは撮り直せない
ので、衝突は報告だけして手を止める。

`*_bk*.csv` はアプリが途中経過を書き出していた頃の名残で、全尺の先頭部分と
一致する。全尺があるものは冗長なので取り込まない（`--include-bk` で変わる）。
現在のアプリは IndexedDB に下書きを持つのでこの名前では出てこない。

**Track B（基板）の `rec.html` は zip 1 個で書き出す**（`mc52_<日付>_<時刻>.zip`）。
中身を振り分ける: `.bin` と測位（`gps_*`）は `private/logs/`、基板ログの CSV（`auto*.csv`）は
`private/csv/`。ばらで落ちてきたもの（古い版のページ）も同じ規則で拾う。
取り込んだ後、`auto` のパートに欠番があれば知らせる（基板にまだ残っていれば `get` で取れる）。
"""

import argparse
import csv
import hashlib
import pathlib
import re
import shutil
import sys
import zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent
DEST = REPO / 'private' / 'logs'
DEST_CSV = REPO / 'private' / 'csv'
# 車両ログのファイル名。`mc52_` が現行、`cb250r_` は 2026-08 中頃までの旧名
PATTERNS = ('mc52_*.csv', 'cb250r_*.csv')


def digest(p):
    return hashlib.md5(p.read_bytes()).hexdigest()


def rows_of(p):
    try:
        with p.open(newline='') as f:
            return sum(1 for _ in csv.reader(f)) - 1
    except OSError:
        return -1


def is_prefix_of(part, whole):
    """part が whole の先頭部分か。**最終行は比べない。**

    途中経過の書き出しは行の途中で撮られるため、最後の 1 行だけ GPS 列が
    全尺版と食い違う（後から新しい測位で埋め直されている）。それ以外の行が
    完全に一致すれば同じ走行の先頭部分と見てよい。
    """
    try:
        a = part.read_text(errors='replace').splitlines()
        b = whole.read_text(errors='replace').splitlines()
    except OSError:
        return False
    return 2 <= len(a) <= len(b) and a[:-1] == b[:len(a) - 1]


def mates(csv_path):
    """CSV と、あれば同名の GPX。"""
    out = [csv_path]
    gpx = csv_path.with_suffix('.gpx')
    if gpx.exists():
        out.append(gpx)
    return out


def do_list():
    files = sorted(p for pat in PATTERNS for p in DEST.glob(pat))
    if not files:
        print(f'{DEST} に走行ログが無い')
        return 0
    print(f'{"ファイル":<34} {"行":>6} {"分":>6}  GPX')
    total = 0
    for p in files:
        n = rows_of(p)
        total += max(n, 0)
        try:
            with p.open(newline='') as f:
                r = list(csv.DictReader(f))
            mins = (float(r[-1]['t_sec']) - float(r[0]['t_sec'])) / 60 if r else 0
        except (OSError, KeyError, ValueError, IndexError):
            mins = 0
        print(f'{p.name:<34} {n:>6} {mins:>6.1f}  '
              f'{"あり" if p.with_suffix(".gpx").exists() else "—"}')
    print(f'\n{len(files)} 本 / {total} 行')
    return 0


def route(name):
    """Track B のファイル名 → 置き場。対象外は None"""
    if re.fullmatch(r'auto\d{4}(_\d+)?\.bin', name) or re.fullmatch(r'gps_[\dT-]+(_\w+)?\.(csv|gpx)', name):
        return DEST
    if re.fullmatch(r'auto\d{4}[a-z]?\.csv', name):
        return DEST_CSV
    return None


def put(name, data, added, same, conflict):
    """1 ファイルを置く。**同名で中身が違えば置かない**（走行ログは撮り直せない）"""
    d = route(name) / name
    if not d.exists():
        d.write_bytes(data)
        added.append(d)
        return True
    if hashlib.md5(data).hexdigest() == digest(d):
        same.append(d)
        return True
    conflict.append(d)
    return False


def track_b(src, move):
    """zip と、ばらの Track B ファイルを取り込む。戻り値は衝突の数"""
    DEST_CSV.mkdir(parents=True, exist_ok=True)
    added, same, conflict, done = [], [], [], []
    for z in sorted(src.glob('mc52_*.zip')):
        ok = True
        with zipfile.ZipFile(z) as zf:
            for i in zf.infolist():
                if route(i.filename) is None:
                    print(f'  ? 振り分け先が無い {z.name}:{i.filename}（取り込まない）')
                    ok = False
                    continue
                ok &= put(i.filename, zf.read(i), added, same, conflict)
        print(f'  zip  {z.name}  {len(zf.infolist())} 件')
        if ok:
            done.append(z)
    for f in sorted(p for p in src.iterdir() if p.is_file() and route(p.name)):
        if put(f.name, f.read_bytes(), added, same, conflict):
            done.append(f)
    for p in added:
        print(f'  取込  {p.relative_to(REPO)}')
    for p in conflict:
        print(f'  ★衝突 {p.name}  同名で中身が違う。手で確認すること')
    if same:
        print(f'  既存  {len(same)} 件（中身一致）')
    if move:
        for f in done:
            f.unlink()
        print(f'  {src} から {len(done)} 個を削除した（取り込み先と一致を確認済み）')
    # 欠番。取り込んだ走行だけ見る
    seqs = {m.group(1) for p in added if (m := re.fullmatch(r'auto(\d{4})_\d+\.bin', p.name))}
    for sq in sorted(seqs):
        nos = sorted(int(re.search(r'_(\d+)\.bin$', p.name).group(1)) for p in DEST.glob(f'auto{sq}_*.bin'))
        miss = sorted(set(range(1, nos[-1] + 1)) - set(nos))
        if miss:
            print(f'  ★欠番 auto{sq}: パート {", ".join(f"{n:02d}" for n in miss)} が無い。'
                  f'基板に残っていれば get auto{sq}_NN.bin')
    if added or conflict:
        print(f'  Track B: 新規 {len(added)} / 既存 {len(same)} / 衝突 {len(conflict)}')
    return len(conflict)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='src', default='~/Downloads', help='取り込み元')
    ap.add_argument('--move', action='store_true', help='一致を確認してから元を消す')
    ap.add_argument('--list', action='store_true', help='private/logs/ の中身を一覧する')
    ap.add_argument('--include-bk', action='store_true', help='_bk も取り込む')
    args = ap.parse_args()

    DEST.mkdir(parents=True, exist_ok=True)
    if args.list:
        return do_list()

    src = pathlib.Path(args.src).expanduser()
    if not src.is_dir():
        print(f'[!] 取り込み元が無い: {src}', file=sys.stderr)
        return 1

    nb = track_b(src, args.move)
    found = sorted({p for pat in PATTERNS for p in src.glob(pat)})
    if not found:
        if not nb:
            print(f'{src} に Track A の走行ログは無い')
        return 1 if nb else 0

    added, same, skipped, conflict = [], [], [], []
    for p in found:
        if '_bk' in p.stem and not args.include_bk:
            # 全尺があるなら冗長。無いなら救出対象なので取り込む
            full = src / (p.stem.split('_bk')[0] + '.csv')
            whole = DEST / full.name if (DEST / full.name).exists() else full
            if whole.exists() and is_prefix_of(p, whole):
                skipped.append((p, f'{whole.name} の先頭部分'))
                continue

        for f in mates(p):
            d = DEST / f.name
            if not d.exists():
                shutil.copy2(f, d)
                added.append(d)
            elif digest(f) == digest(d):
                same.append(f)
            else:
                conflict.append(f)

    for p in added:
        print(f'  取込  {p.name}  ({rows_of(p)} 行)' if p.suffix == '.csv'
              else f'  取込  {p.name}')
    for p in skipped:
        print(f'  除外  {p[0].name}  ({p[1]})')
    for p in same:
        print(f'  既存  {p.name}  （中身一致）')
    for p in conflict:
        print(f'  ★衝突 {p.name}  同名で中身が違う。手で確認すること')

    if args.move:
        # 取り込み済み（新規＋一致）だけ消す。衝突と除外は残す
        movable = [f for f in added] + list(same)
        gone = 0
        for f in movable:
            s = src / f.name
            if s.exists() and (DEST / f.name).exists() and digest(s) == digest(DEST / f.name):
                s.unlink()
                gone += 1
        print(f'\n{src} から {gone} 個を削除した（コピー先と一致を確認済み）')

    print(f'\n新規 {len(added)} / 既存 {len(same)} / 除外 {len(skipped)} / 衝突 {len(conflict)}')
    return 1 if conflict or nb else 0


if __name__ == '__main__':
    sys.exit(main())
