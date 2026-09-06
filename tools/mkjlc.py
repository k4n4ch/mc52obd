#!/usr/bin/env python3
"""EasyEDA が書き出した BOM と実装座標を、JLCPCB の PCBA へ渡せる形にする。

**ガーバーだけを上げると基板単体（PCB）になる。** 実装を頼むには注文画面で
`PCB Assembly` を有効にし、ここで作る 2 つを上げる。それで初めて部品込みの
プレビューが出る。

2 つ直すことがある。

1. **列名。** JLCPCB は `Comment` / `Designator` / `Footprint` / `LCSC Part #` と
   `Designator` / `Mid X` / `Mid Y` / `Layer` / `Rotation` を見る。EasyEDA の
   書き出しは LCSC 番号を `Supplier Part` という名前で持っている
2. **実装しない部品を外す。** `J1` `J2` は手ハンダ、`J3` は部品を載せない。
   残すと要らないコネクタまで実装され、Extended の手配料も乗る

    python3 tools/mkjlc.py
"""

import csv
import io
import pathlib

HW = pathlib.Path(__file__).resolve().parent.parent / 'hardware'
SKIP = {'J1', 'J2', 'J3'}          # 手ハンダ / 実装しない


def read_utf16_tsv(path):
    rows = list(csv.reader(io.open(path, encoding='utf-16'), delimiter='\t'))
    head = [c.strip().strip('"') for c in rows[0]]
    return head, [[c.strip().strip('"') for c in r] for r in rows[1:] if any(r)]


def main():
    bh, brows = read_utf16_tsv(HW / 'Export_BOM.csv')
    ci = {k: bh.index(k) for k in ('Supplier Part', 'Comment', 'Footprint', 'Designator')}
    out, dropped = [], []
    for r in brows:
        des = [d.strip() for d in r[ci['Designator']].split(',') if d.strip()]
        keep = [d for d in des if d not in SKIP]
        if not keep:
            dropped.append(','.join(des)); continue
        if len(keep) != len(des):
            dropped.append(','.join(d for d in des if d in SKIP))
        out.append([r[ci['Comment']], ','.join(keep), r[ci['Footprint']], r[ci['Supplier Part']]])
    with io.open(HW / 'jlc_bom.csv', 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['Comment', 'Designator', 'Footprint', 'LCSC Part #'])
        w.writerows(out)
    print(f'jlc_bom.csv  {len(out)} 品種 / 実装 {sum(len(r[1].split(",")) for r in out)} 点'
          + (f' / 外した {" ".join(dropped)}' if dropped else ''))

    ph, prows = read_utf16_tsv(HW / 'Pick_Place')
    pi = {k: ph.index(k) for k in ('Designator', 'Mid X', 'Mid Y', 'Layer', 'Rotation')}
    cpl = [[r[pi['Designator']], r[pi['Mid X']], r[pi['Mid Y']],
            'Top' if r[pi['Layer']] in ('T', 'Top') else 'Bottom', r[pi['Rotation']]]
           for r in prows if r[pi['Designator']] not in SKIP]
    with io.open(HW / 'jlc_cpl.csv', 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['Designator', 'Mid X', 'Mid Y', 'Layer', 'Rotation'])
        w.writerows(cpl)
    print(f'jlc_cpl.csv  {len(cpl)} 部品')

    bset = {d for r in out for d in r[1].split(',')}
    cset = {r[0] for r in cpl}
    if bset != cset:
        print(f'  **BOM と座標が食い違う** BOM のみ {sorted(bset-cset)} / 座標のみ {sorted(cset-bset)}')
    else:
        print(f'  BOM と座標の参照名が一致（{len(bset)} 点）')


if __name__ == '__main__':
    main()
