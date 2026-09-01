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
"""

import argparse
import csv
import hashlib
import pathlib
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
DEST = REPO / 'private' / 'logs'
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

    found = sorted({p for pat in PATTERNS for p in src.glob(pat)})
    if not found:
        print(f'{src} に走行ログは無い')
        return 0

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
    return 1 if conflict else 0


if __name__ == '__main__':
    sys.exit(main())
