/* MC52 基板のケース（PETG で 3D プリント）
 *
 * 基板は ../hardware/。50 × 40mm、取付穴 φ2.8（M2.5）が各辺から 3.5mm。
 * **探索＋記録フェーズ用の窓なし密閉箱。** 表示器が未決なので窓は付けない。
 *
 * ── 実測（2026-09-15）────────────────────────────────────
 *   C2（電解）の高さ      8mm
 *   J1 の熱収縮まで      12mm   ← **これが内寸を支配する**
 *   線が曲がり始める     20mm
 *   シースの下端         33mm   外径 6mm
 *
 * **蓋の J1 直上から線を真っ直ぐ抜く。** ケース内で曲げようとすると内寸 22mm
 * 以上になるが、外で曲げれば 13mm で済む（外形で 9mm 低い）。
 */

// ── 基板 ─────────────────────────────────────────────────
PCB_X = 50.0; PCB_Y = 40.0; PCB_T = 1.6;
HOLE_IN = 3.5; HOLE_D = 2.8;
J1_X = 2.54; J1_Y = 7.62; J1_PITCH = 2.54;   // ../hardware/Net_List.enet

H_J1 = 12.0;   // 熱収縮の頂点。内寸を支配する
H_C2 = 8.0;

// ── ケース ───────────────────────────────────────────────
WALL  = 2.0;   // 0.4mm ノズルで 5 周。強度も気密も足りる
FLOOR = 2.5;   // タイラップ溝を彫っても 1.5mm 残る
LIDT  = 2.5;
CLR   = 0.4;   // 基板と内壁の片側隙間
STANDOFF = 3.0;   // 基板下の逃げ。J1 のピンが裏へ突き出る
HEAD     = 1.0;   // J1 頂点と蓋裏の隙間

/* 基板を受ける柱の径。**φ5.8 だと J1 の線と 0.17mm 干渉する。**
 * 取付穴 (3.5,3.5) から J1 の 1 番ピン (2.54,7.62) まで 4.23mm しかなく、
 * 熱収縮の半径を 1.5mm と見ると柱の半径は 2.7mm 未満でなければならない。
 * hardware/README.md の「M2.5 の頭でも余裕 0.30mm」と同じ制約。 */
BOSS_D = HOLE_D + 2.0;   // = 4.8。半径 2.4 + 1.5 = 3.9 < 4.23（余裕 0.33mm）

INNER_X = PCB_X + 2*CLR;
INNER_Y = PCB_Y + 2*CLR;
INNER_Z = STANDOFF + PCB_T + H_J1 + HEAD;

/* 蓋ネジ。**四隅の局所的な耳にする。**
 * 柱を外殻に含めると外周が全部その直径ぶん埋まり、片側 7mm の肉になって無駄。
 * 耳の中心をキャビティの角から対角に LUG_OFF 出すとき、半径 2.5mm の柱が
 * キャビティへ食い込まない条件は LUG_OFF × √2 ≥ 2.5、すなわち 1.77mm 以上。 */
SCREW_D = 2.5; SCREW_PIL = 2.1; LUG = 5.0;
LUG_OFF = 2.0;              // 2.0 × √2 = 2.83 > 2.5 ✓
EAR = LUG_OFF + LUG/2;      // 角だけ張り出す量 = 4.5

CASE_X = INNER_X + 2*WALL;
CASE_Y = INNER_Y + 2*WALL;

/* ケーブル出口。**縁まで開いた U 溝。**
 * 閉じた長穴だと蓋が入らない —— 線は既に J1 へハンダ付け済みで、蓋を上から
 * 通すにはケーブルの反対端（4 ピンカプラ）を長穴に通す必要があるが、通らない。
 * 溝は線が一列に並んでいる x 方向へ抜く（幅 4.6mm で済み、y 方向より開口が小さい）。 */
CBL_W = 8.4; CBL_L = 4.6; CBL_BOSS = 6.0; CBL_WALL = 2.0;

/* タイラップ。**溝にして底を貫かない。** 壁が 2.0mm しかないのでトンネルを
 * 掘るとキャビティへ抜ける。ケースの外周を一周させ、帯が滑らないよう底と蓋の
 * 両方に溝を彫る。締めた帯が蓋を押さえる働きも兼ねる。 */
TIE_W = 5.0; TIE_D = 1.0;

$fn = 48;

function px(x) = x + CLR;
function py(y) = y + CLR;
CBL_CX = px(J1_X + J1_PITCH);
CBL_CY = py(J1_Y);

module rrect(x, y, z, r) {
  hull() for (a = [r, x - r], b = [r, y - r]) translate([a, b, 0]) cylinder(r = r, h = z);
}
module hole_positions() {
  for (x = [HOLE_IN, PCB_X - HOLE_IN], y = [HOLE_IN, PCB_Y - HOLE_IN])
    translate([px(x), py(y), 0]) children();
}
module lug_positions() {
  for (x = [-LUG_OFF, INNER_X + LUG_OFF], y = [-LUG_OFF, INNER_Y + LUG_OFF])
    translate([x, y, 0]) children();
}
module tie_cut(z) {
  for (y = [INNER_Y*0.28, INNER_Y*0.72])
    translate([-WALL - EAR - 1, y - TIE_W/2, z]) cube([CASE_X + 2*EAR + 2, TIE_W, TIE_D + 0.02]);
}

// ── 本体 ─────────────────────────────────────────────────
module base() {
  difference() {
    union() {
      translate([-WALL, -WALL, 0]) rrect(CASE_X, CASE_Y, FLOOR + INNER_Z, 2.0);
      lug_positions() cylinder(d = LUG, h = FLOOR + INNER_Z);          // 四隅の耳
    }
    translate([0, 0, FLOOR]) cube([INNER_X, INNER_Y, INNER_Z + 1]);    // キャビティ
    lug_positions() translate([0, 0, FLOOR + INNER_Z - 8]) cylinder(d = SCREW_PIL, h = 9);
    tie_cut(-0.01);                                                    // 底のタイラップ溝
  }
  /* **基板を受ける柱はキャビティを彫った後に足す。**
   * difference の中で union すると、キャビティの立方体が柱ごと削ってしまう。 */
  difference() {
    hole_positions() cylinder(d = BOSS_D, h = FLOOR + STANDOFF);
    hole_positions() translate([0, 0, FLOOR]) cylinder(d = SCREW_PIL, h = STANDOFF + 1);
  }
}

// ── 蓋 ───────────────────────────────────────────────────
module lid() {
  LIP_T = 1.5;
  difference() {
    union() {
      translate([-WALL, -WALL, 0]) rrect(CASE_X, CASE_Y, LIDT, 2.0);
      lug_positions() cylinder(d = LUG, h = LIDT);
      /* 内側に落ちる縁。蓋を位置決めし、合わせ面のシリコンに迷路を作る。
       * **枠にすること。** 中実にすると基板上面より下へ降りて J1 の熱収縮に当たる。 */
      translate([0.3, 0.3, -1.2]) difference() {
        cube([INNER_X - 0.6, INNER_Y - 0.6, 1.2]);
        translate([LIP_T, LIP_T, -0.5])
          cube([INNER_X - 0.6 - 2*LIP_T, INNER_Y - 0.6 - 2*LIP_T, 2.2]);
      }
      // ケーブルの樋。端は外形と面一にする（はみ出すと引っ掛かる）
      translate([0, CBL_CY, LIDT])
        hull() for (x = [CBL_CX + (CBL_W - CBL_L)/2, -WALL + (CBL_L + 2*CBL_WALL)/2])
          translate([x, 0, 0]) cylinder(d = CBL_L + 2*CBL_WALL, h = CBL_BOSS);
    }
    // U 溝（樋・縁ごと貫通し、-x の縁まで開く）
    translate([0, CBL_CY, -2])
      hull() for (x = [CBL_CX + (CBL_W - CBL_L)/2, -WALL - EAR - 2])
        translate([x, 0, 0]) cylinder(d = CBL_L, h = LIDT + CBL_BOSS + 4);
    // 蓋のネジ穴（頭を落とす）
    lug_positions() {
      translate([0, 0, -1]) cylinder(d = SCREW_D + 0.4, h = LIDT + 2);
      translate([0, 0, LIDT - 1.4]) cylinder(d = SCREW_D + 2.6, h = 2);
    }
    // 縁が基板の取付穴の柱と当たらないよう逃がす
    hole_positions() translate([0, 0, -1.6]) cylinder(d = HOLE_D + 4.0, h = 2.0);
    tie_cut(LIDT - TIE_D);                                             // 上面のタイラップ溝
  }
}

PART = "both";
if (PART == "base" || PART == "both") base();
if (PART == "lid"  || PART == "both") translate([0, CASE_Y + 2*EAR + 6, 0]) lid();
