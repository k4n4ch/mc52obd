#!/usr/bin/env python3
"""ログの絶対時刻をずらす。公開用に走行日時を伏せるため。

**ずらした時刻は捏造値。** 実データと取り違えないよう、適用したファイルは
その旨を明記して扱うこと。位置情報は一切変えないので、これだけでは
走行場所は伏せられない。

`t_sec` は相対値なので触らない。CSV の `iso_time` と GPX の `<time>` を同じ量
だけ動かす。同名の `.gpx` があれば一緒に処理する。

    python3 tools/shifttime.py private/seg....csv --days -2 --time -3:33
"""
import argparse, csv, datetime as dt, os, re, sys

ISO = '%Y-%m-%dT%H:%M:%S.%f'


def shift_iso(s, delta):
    z = s.endswith('Z')
    t = dt.datetime.strptime(s[:-1] if z else s, ISO if '.' in s else '%Y-%m-%dT%H:%M:%S')
    t += delta
    out = t.strftime(ISO)[:-3] if '.' in s else t.strftime('%Y-%m-%dT%H:%M:%S')
    return out + ('Z' if z else '')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('--days', type=int, default=0)
    ap.add_argument('--time', default='0:00', help='HH:MM。先頭の - で負')
    ap.add_argument('-o', '--out', help='省略時は上書き')
    a = ap.parse_args()

    neg = a.time.startswith('-')
    hh, mm = (a.time.lstrip('+-') + ':0').split(':')[:2]
    d = dt.timedelta(hours=int(hh), minutes=int(mm))
    delta = dt.timedelta(days=a.days) + (-d if neg else d)

    out = a.out or a.src
    rows = list(csv.DictReader(open(a.src)))
    if not rows or 'iso_time' not in rows[0]:
        sys.exit('iso_time 列が無い')
    before = rows[0]['iso_time']
    for r in rows:
        if r['iso_time']:
            r['iso_time'] = shift_iso(r['iso_time'], delta)
    with open(out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f'{out}: {len(rows)} 行  {before} → {rows[0]["iso_time"]}  （{delta}）')

    gsrc = os.path.splitext(a.src)[0] + '.gpx'
    if os.path.exists(gsrc):
        gout = os.path.splitext(out)[0] + '.gpx'
        txt = open(gsrc, encoding='utf-8').read()
        n = 0
        def rep(m):
            nonlocal n
            n += 1
            return f'<time>{shift_iso(m.group(1), delta)}</time>'
        txt = re.sub(r'<time>([^<]+)</time>', rep, txt)
        open(gout, 'w', encoding='utf-8').write(txt)
        print(f'{gout}: {n} 点')


if __name__ == '__main__':
    main()
