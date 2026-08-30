#!/usr/bin/env python3
"""走行ログから時間区間を切り出す。

例示用に「速度超過が写り込まない区間」だけを取り出すのに使う。
`t_sec` は 0 起点へ振り直し、先頭行のセッション条件（app/proto/p3/sprocket_f）は
切り出し後の先頭行へ引き継ぐ。列は増減させない。

同名の `.gpx` があれば、CSV の `iso_time` から求めた絶対時刻の窓で一緒に切る。
GPX は OBD と独立に測位しているので点数も間隔も CSV とは一致しない。
`<trkseg>` の切れ目（測位途絶）は元の分割を保つ。

    python3 tools/cutlog.py private/mc52_....csv 3286 3883 -o out.csv
"""
import argparse, csv, os, re, sys

META = ('app', 'proto', 'p3', 'sprocket_f')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('t0', type=float, help='開始 t_sec')
    ap.add_argument('t1', type=float, help='終了 t_sec')
    ap.add_argument('-o', '--out', required=True)
    a = ap.parse_args()

    rows = list(csv.DictReader(open(a.src)))
    if not rows:
        sys.exit('空のファイル')
    head = list(rows[0].keys())
    meta = {k: rows[0].get(k, '') for k in META if k in head}

    sel = [r for r in rows if a.t0 <= float(r['t_sec']) <= a.t1]
    if not sel:
        sys.exit('該当する行が無い')

    base = float(sel[0]['t_sec'])
    for i, r in enumerate(sel):
        r['t_sec'] = f"{float(r['t_sec']) - base:.2f}"
        for k in META:
            if k in head:
                r[k] = meta[k] if i == 0 else ''

    with open(a.out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=head)
        w.writeheader()
        w.writerows(sel)

    sp = [float(r['speed_obd']) for r in sel if r.get('speed_obd')]
    true = [(v + 0.5) * 15 / 14 for v in sp]      # ECU 生値 → 実車速（15T）
    print(f'{a.out}: {len(sel)} 行 / {float(sel[-1]["t_sec"])/60:.1f} 分')
    print(f'  実車速 平均 {sum(true)/len(true):.1f} / 最大 {max(true):.1f} km/h')

    cut_gpx(a.src, a.out, sel[0]['iso_time'], sel[-1]['iso_time'])


def cut_gpx(src, out, iso0, iso1):
    """同名の GPX を同じ絶対時刻の窓で切る。無ければ何もしない。"""
    gsrc = os.path.splitext(src)[0] + '.gpx'
    if not (iso0 and iso1 and os.path.exists(gsrc)):
        return
    text = open(gsrc, encoding='utf-8').read()
    m = re.search(r'(.*?)<trkseg>', text, re.S)
    if not m:
        print('  GPX: <trkseg> が見つからない'); return
    header = m.group(1)
    segs = re.findall(r'<trkseg>(.*?)</trkseg>', text, re.S)
    kept, n = [], 0
    for seg in segs:
        pts = [p for p in re.findall(r'<trkpt.*?</trkpt>', seg, re.S)
               if (t := re.search(r'<time>([^<]+)</time>', p)) and iso0 <= t.group(1) <= iso1]
        if pts:
            kept.append(pts); n += len(pts)
    if not n:
        print('  GPX: 窓に入る点が無い'); return
    gout = os.path.splitext(out)[0] + '.gpx'
    with open(gout, 'w', encoding='utf-8') as f:
        f.write(header)                       # 冒頭〜最初の <trkseg> の直前まで
        f.write('<trkseg>\n')
        f.write('\n</trkseg>\n  <trkseg>\n'.join('\n'.join(s) for s in kept))
        f.write('\n</trkseg>\n  </trk>\n</gpx>\n')
    print(f'  {gout}: {n} 点 / {len(kept)} セグメント')


if __name__ == '__main__':
    main()
