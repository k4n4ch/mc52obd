/* ケースの干渉検査。**目視ではなく交差を取って確かめる。**
 * レンダは当てにならない（柱が壁に溶けて数え間違えた実績がある）。
 *
 *   for t in lid_wire lid_shrink lid_parts base_parts standoffs post_slot; do
 *     openscad -D 'PART="none"' -D "TEST=\"$t\"" -o /tmp/t.stl check.scad
 *   done
 *
 * 「empty」が出れば干渉なし。**寸法を変えたら必ず回す。**
 */
include <mc52case.scad>;
include <parts.scad>;      // genparts.py が製造データから生成

W_D = 2.5;    // 線の外径（余裕込み）
S_D = 3.2;    // 熱収縮の外径
S_H = 12.0;   // 熱収縮の頂点（基板面から）

module wires(d, h0, h1) {
  for (i = [0, 1, 2])
    translate([px(J1_X + i*J1_PITCH), py(J1_Y), PCB_TOP + h0]) cylinder(d = d, h = h1 - h0);
}
module lid_placed() { translate([0, 0, LID_Z]) lid(); }

TEST = "none";

if (TEST == "lid_wire")   intersection() { lid_placed(); wires(W_D, 0, 40); }
if (TEST == "lid_shrink") intersection() { lid_placed(); wires(S_D, 0, S_H); }
if (TEST == "lid_parts")  intersection() { lid_placed(); pcb_parts(); }   // 蓋の柱 × 全 26 部品
if (TEST == "base_parts") intersection() { base(); pcb_parts(); }
/* 蓋の柱が U 溝に削られていないか。
 * **円盤で突いてはいけない** —— 柱には素通し穴（φ2.2）が開いているので中心は必ず欠ける。
 * 穴（半径 1.1）と外周（半径 2.0）の間、半径 1.55mm の円周上を 8 点で突く。 */
if (TEST == "post_slot")
  difference() {
    post_positions()
      for (a = [0 : 45 : 359])
        translate([1.55*cos(a), 1.55*sin(a), LID_Z - POST_H/2]) sphere(d = 0.6);
    lid_placed();
  }
/* 本体の柱が 4 本とも在るか（下穴と外周の間を突く） */
if (TEST == "standoffs")
  difference() {
    hole_positions() translate([1.7, 0, FLOOR + STANDOFF/2]) sphere(d = 0.8);
    base();
  }
