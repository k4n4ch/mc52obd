"""製造データから部品の外形を OpenSCAD のモデルに起こす。

**蓋の柱は基板面まで 13mm 降りるので、XY で重なれば高さに関係なく当たる。**
だから高さの実測が無い部品も、外形さえ分かれば検査できる。

L / W はフットプリント名から取る（`SMA_L4.3-W2.6-…` のような命名）。
位置と回転は ../hardware/Pick_Place（JLCPCB に送った実装座標そのもの）。
"""
import csv, io, re, sys

H = {"C2": 8.0, "U2": 3.1}        # 実測のあるもの
H_DEFAULT = 3.0                    # 他は余裕を見て 3mm とする（XY 検査が目的）

fp = {}
for r in csv.DictReader(io.open("../hardware/jlc_bom.csv", encoding="utf-8")):
    for d in r["Designator"].replace('"', "").split(","):
        fp[d.strip()] = r.get("Footprint", "")

rows = list(csv.reader(io.open("../hardware/Pick_Place", encoding="utf-16"), delimiter="\t"))
hdr = [c.strip().strip('"') for c in rows[0]]
ix = {k: hdr.index(k) for k in ("Designator", "Mid X", "Mid Y", "Rotation")}
mm = lambda s: float(s.strip().strip('"').replace("mm", ""))

# J1 / J2 は手ハンダで BOM に無いが、蓋の柱が当たるかの検査には要る
fp.setdefault("J1", "HDR_L10.2-W2.5")
fp.setdefault("J2", "HDR_L15.2-W2.5")

out = ["// genparts.py が生成。手で直さない。", "module pcb_parts() {"]
n = 0
for r in rows[1:]:
    if not r or len(r) < len(hdr):
        continue
    d = r[ix["Designator"]].strip().strip('"')
    f = fp.get(d, "")
    L = re.search(r"[-_]L([\d.]+)", f)
    W = re.search(r"[-_]W([\d.]+)", f)
    BD = re.search(r"BD([\d.]+)", f)
    IMP = re.match(r"^[RCL](\d{4})$", f)   # R0603 / C1210 のようなインチコード
    if IMP:
        c = IMP.group(1)
        l, w = int(c[:2]) * 0.254, int(c[2:]) * 0.254
    elif BD:                        # 円筒（電解）
        l = w = float(BD.group(1))
    elif L and W:
        l, w = float(L.group(1)), float(W.group(1))
    elif "ESP32-S3-WROOM-1" in f:
        l, w = 18.0, 25.5
    else:
        print(f"  ★ 外形が取れない: {d} ({f})", file=sys.stderr)
        continue
    x, y, rot = mm(r[ix["Mid X"]]), mm(r[ix["Mid Y"]]), mm(r[ix["Rotation"]])
    if int(rot) % 180 == 90:
        l, w = w, l
    h = H.get(d, H_DEFAULT)
    out.append(f"  translate([px({x:.2f}) - {l/2:.2f}, py({y:.2f}) - {w/2:.2f}, PCB_TOP]) "
               f"cube([{l:.2f}, {w:.2f}, {h:.1f}]);   // {d}")
    n += 1
out.append("}")
io.open("parts.scad", "w", encoding="utf-8").write("\n".join(out) + "\n")
print(f"{n} 部品を書き出した")
