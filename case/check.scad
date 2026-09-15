/* 干渉検査。**目視ではなく交差を取って確かめる。**
 * 線・熱収縮・部品を円柱と直方体でモデル化し、ケースとの交差が空かを見る。
 * 空でなければ OpenSCAD が「top level object is empty」を出さないので分かる。
 *
 *   openscad -D 'TEST="lid_wire"' -o /tmp/t.stl check.scad
 */
include <mc52case.scad>;

PCB_TOP = FLOOR + STANDOFF + PCB_T;   // 6.6
LID_Z   = FLOOR + INNER_Z;            // 19.6（蓋の裏）

W_D     = 2.5;    // 線の外径（余裕込み）
S_D     = 3.2;    // 熱収縮の外径
S_H     = 12.0;   // 熱収縮の頂点（基板面から）

module wires(d, h0, h1) {
  for (i = [0, 1, 2])
    translate([px(J1_X + i*J1_PITCH), py(J1_Y), PCB_TOP + h0])
      cylinder(d = d, h = h1 - h0);
}
// 背の高い部品
module parts() {
  translate([px(15.82) - 3.5, py(13.21) - 3.5, PCB_TOP]) cube([7, 7, H_C2]);      // C2
  translate([px(34.04) - 9.5, py(23.37) - 13, PCB_TOP])  cube([19, 26, 3.1]);     // U2
}

TEST = "all";

// 蓋（組み立て位置）と線
if (TEST == "lid_wire")
  intersection() { translate([0,0,LID_Z]) lid(); wires(W_D, 0, 40); }
// 蓋と熱収縮
if (TEST == "lid_shrink")
  intersection() { translate([0,0,LID_Z]) lid(); wires(S_D, 0, S_H); }
// 蓋と背の高い部品
if (TEST == "lid_parts")
  intersection() { translate([0,0,LID_Z]) lid(); parts(); }
// 本体（柱・壁）と熱収縮
if (TEST == "base_shrink")
  intersection() { base(); wires(S_D, 0, S_H); }
// 本体と背の高い部品
if (TEST == "base_parts")
  intersection() { base(); parts(); }
