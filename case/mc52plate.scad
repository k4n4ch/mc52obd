/* MC52 基板の仮組みプレート
 *
 * **M2 × 20 のネジが届くまでの繋ぎ。** 板＋スナップ足で基板を保持する。
 * 本番はケース（mc52case.scad）で、こちらは机上で基板を扱いやすくするだけ。
 *
 * 足は 2 種類を切り替えられる。
 *   "snap"  … 先端が 3 つに割れていて弾性で嵌まる（Arduino のプレートによくある形）
 *   "press" … 割らずに締まり嵌め。**スナップが折れたらこちら**
 *
 * **スナップ足は PETG だと折れやすい。** 縦に印刷すると曲げが積層方向に入るため。
 * 仮組み用なので許容するが、何度も抜き差しするなら press のほうが保つ。
 */

// ── 基板（../hardware/）────────────────────────────────────
PCB_X = 50.0; PCB_Y = 40.0; PCB_T = 1.6;
HOLE_IN = 3.5; HOLE_D = 2.8;

// ── プレート ─────────────────────────────────────────────
MARGIN = 2.0;                 // 基板からの張り出し
PLATE_T = 2.5;
STANDOFF = 3.0;               // ケースと同じ。J1 のピンが裏へ突き出るぶん
SHOULDER_D = 5.0;             // 基板を受ける座

POST = "snap";                // "snap" / "press"

// スナップ
SHAFT_D = HOLE_D - 0.2;       // 2.6。穴 2.8 に対して片側 0.1 の隙間
BARB_D  = HOLE_D + 0.6;       // 3.4。掛かりは片側 0.3mm
BARB_H  = 1.8;                // 抜け止めの円錐の高さ
LEAD    = 0.6;                // 先端の面取り（入れやすさ）
SLOTS   = 3;                  // 割りの本数
SLOT_W  = 0.8;
SLOT_DEEP = 2.0;              // 座の中まで切り込んで足を長くする＝曲がりやすくする

// 圧入（スナップが折れたとき用）
PRESS_D = HOLE_D + 0.05;      // 2.85。PETG の縮みを見て気持ち太らせる

$fn = 48;

module hole_positions() {
  for (x = [HOLE_IN, PCB_X - HOLE_IN], y = [HOLE_IN, PCB_Y - HOLE_IN])
    translate([x + MARGIN, y + MARGIN, 0]) children();
}
module rrect(x, y, z, r) {
  hull() for (a = [r, x - r], b = [r, y - r]) translate([a, b, 0]) cylinder(r = r, h = z);
}

module snap_post() {
  z0 = PLATE_T;
  difference() {
    union() {
      cylinder(d = SHOULDER_D, h = z0 + STANDOFF);               // 座
      translate([0, 0, z0 + STANDOFF])
        cylinder(d = SHAFT_D, h = PCB_T + 0.1);                  // 板厚を通る軸
      // 抜け止め。下が太く上が細い円錐なので、押し込むと足が内へ逃げる
      translate([0, 0, z0 + STANDOFF + PCB_T + 0.1])
        cylinder(d1 = BARB_D, d2 = SHAFT_D - LEAD, h = BARB_H);
    }
    // 割り。座の中まで切り込んで足を長くする
    for (i = [0 : SLOTS - 1])
      rotate([0, 0, i * 360 / SLOTS])
        translate([-SLOT_W/2, -0.01, z0 + STANDOFF - SLOT_DEEP])
          cube([SLOT_W, BARB_D, PCB_T + BARB_H + SLOT_DEEP + 1]);
  }
}

module press_post() {
  cylinder(d = SHOULDER_D, h = PLATE_T + STANDOFF);
  translate([0, 0, PLATE_T + STANDOFF]) {
    cylinder(d = PRESS_D, h = PCB_T);
    translate([0, 0, PCB_T]) cylinder(d1 = PRESS_D, d2 = PRESS_D - 0.8, h = 0.6);  // 面取り
  }
}

module plate() {
  rrect(PCB_X + 2*MARGIN, PCB_Y + 2*MARGIN, PLATE_T, 2.0);
  hole_positions() { if (POST == "snap") snap_post(); else press_post(); }
}

plate();
