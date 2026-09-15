/* MC52 基板のケース（PETG で 3D プリント）
 *
 * 基板は ../hardware/。50 × 40mm、取付穴 φ2.8（M2.5）が各辺から 3.5mm。
 *
 * **探索＋記録フェーズ用の窓なし密閉箱。** 表示器が未決なので窓は付けない。
 * 決まったら DISP_* を足して再出力する。
 *
 * ── 寸法を決めた根拠（実測 2026-09-15）────────────────────
 *   C2（電解）の高さ          8mm
 *   J1 の熱収縮まで           12mm   ← **これが内寸を支配する**
 *   線が曲がり始める          20mm
 *   シースの下端              33mm   外径 6mm
 *
 * **蓋の J1 直上から線を真っ直ぐ抜く。** ケース内で曲げようとすると内寸 22mm
 * 以上になるが、外で曲げれば 13mm で済む（外形で 9mm 低い）。
 *
 * **シースは蓋を貫かない。** 33mm と高く、しかも熱収縮を被せた端子 3 本が
 * 約 7.6mm 幅あって内径 6mm のシースに入らないので下げられない。蓋を通るのは
 * バラの 3 本で、ボスにシリコンを充填して塞ぐ。ボスが充填の深さとストレイン
 * リリーフを兼ねる。
 *
 * **蓋のネジは基板の外側に出す。** 取付穴 (3.5,3.5) は J1 の 1 番ピン
 * (2.54,7.62) から 4.23mm しかなく、M2.5 の頭でも余裕 0.30mm（hardware/README.md）。
 * ここにボスを下ろすと線を押す。
 */

// ── 基板 ─────────────────────────────────────────────────
PCB_X    = 50.0;
PCB_Y    = 40.0;
PCB_T    = 1.6;
HOLE_IN  = 3.5;    // 取付穴の中心が各辺から
HOLE_D   = 2.8;    // φ2.8（M2.5）

// J1 の位置（../hardware/Net_List.enet と Pick_Place から）
J1_X     = 2.54;   // 1 番ピンの x（2.54mm ピッチで 4 本）
J1_Y     = 7.62;
J1_PITCH = 2.54;

// ── 実測（2026-09-15）──────────────────────────────────
H_J1     = 12.0;   // 熱収縮の頂点まで。内寸を支配する
H_C2     = 8.0;    // 電解コンデンサ

// ── ケース ───────────────────────────────────────────────
WALL     = 2.5;    // PETG。薄いと層間から漏れる
FLOOR    = 2.0;
LIDT     = 2.5;
CLR      = 0.4;    // 基板と内壁の片側隙間
STANDOFF = 3.0;    // 基板下の逃げ。J1 のピンが裏へ突き出るため
/* 柱の径。**φ5.8 だと J1 の線と 0.17mm 干渉する。**
 * 取付穴 (3.5,3.5) の中心から J1 の 1 番ピン (2.54,7.62) まで 4.23mm しかなく、
 * 熱収縮の半径を 1.5mm と見ると柱の半径は 2.7mm 未満でなければならない。
 * hardware/README.md の「M2.5 の頭でも余裕 0.30mm」と同じ制約。 */
BOSS_D   = HOLE_D + 2.0;   // = 4.8。半径 2.4 + 1.5 = 3.9 < 4.23（余裕 0.33mm）
HEAD     = 1.0;    // J1 頂点と蓋裏の隙間

INNER_X  = PCB_X + 2*CLR;
INNER_Y  = PCB_Y + 2*CLR;
INNER_Z  = STANDOFF + PCB_T + H_J1 + HEAD;   // = 18.1

// 蓋ネジ（基板の外側）
SCREW_D   = 2.5;
SCREW_PIL = 2.1;   // M2.5 タッピングの下穴
LUG       = 5.0;   // ネジ柱の直径
LUG_OFF   = WALL + LUG/2 - 0.5;   // 内壁から柱の中心まで外へ

// ネジ柱を外殻に完全に含める（はみ出すと蓋と外形が食い違う）
SHELL    = LUG_OFF + LUG/2;
CASE_X   = INNER_X + 2*SHELL;
CASE_Y   = INNER_Y + 2*SHELL;

/* ケーブル出口。**縁まで開いた U 溝にする。**
 * 閉じた長穴だと蓋が入らない —— 線は既に J1 へハンダ付け済みで、蓋を上から
 * 通すにはケーブルの反対端（4 ピンカプラ）を長穴に通す必要があるが、通らない。
 *
 * 組み立て: 壁の高さで蓋を横にずらして線を溝の口から入れる → 1.2mm 落として
 * 縁を噛ませる。線は縦のまま曲げずに済む。
 *
 * 溝は J1 の線が一列に並んでいる **x 方向へ抜く**。幅が 4.6mm で済み、
 * y 方向へ抜くより開口が小さい（＝塞ぐシリコンが少なくて済む）。 */
CBL_W    = 8.4;    // 3 ピン分（2×2.54）＋ 熱収縮の太り
CBL_L    = 4.6;    // 溝の幅。線の横入れにも足りる
CBL_BOSS = 6.0;    // 蓋から立てる樋の高さ。シリコン充填の深さになる
CBL_WALL = 2.0;    // 樋の肉厚

// タイラップのスリット（底面）
TIE_W    = 4.0;
TIE_T    = 2.0;

$fn = 48;

// 基板座標 → ケース内座標
function px(x) = x + CLR;
function py(y) = y + CLR;

module hole_positions() {
  for (x = [HOLE_IN, PCB_X - HOLE_IN], y = [HOLE_IN, PCB_Y - HOLE_IN])
    translate([px(x), py(y), 0]) children();
}
module lug_positions() {
  for (x = [-LUG_OFF, INNER_X + LUG_OFF], y = [-LUG_OFF, INNER_Y + LUG_OFF])
    translate([x, y, 0]) children();
}
// ケーブル出口の中心（J1 の 1〜3 番の中央）
CBL_CX = px(J1_X + J1_PITCH);
CBL_CY = py(J1_Y);

module rrect(x, y, z, r) {
  hull() for (a = [r, x - r], b = [r, y - r]) translate([a, b, 0]) cylinder(r = r, h = z);
}

// ── 本体 ─────────────────────────────────────────────────
module base() {
  difference() {
    // 外殻
    translate([-SHELL, -SHELL, 0])
      rrect(CASE_X, CASE_Y, FLOOR + INNER_Z, 2.5);
    // 内側を彫る
    translate([0, 0, FLOOR]) cube([INNER_X, INNER_Y, INNER_Z + 1]);
    // タイラップのスリット（底を貫通させず、外側に橋を作る）
    for (y = [INNER_Y*0.28, INNER_Y*0.72])
      for (sx = [-1, 1])
        translate([sx > 0 ? INNER_X + WALL - 0.01 : -SHELL - 0.01, y - TIE_W/2, 0.01])
          cube([SHELL - WALL + 0.5, TIE_W, TIE_T]);
  }
  /* **基板を受ける柱はキャビティを彫った後に足す。**
   * difference の中で union すると、キャビティの立方体が柱ごと削ってしまう。 */
  difference() {
    hole_positions() cylinder(d = BOSS_D, h = FLOOR + STANDOFF);
    hole_positions() translate([0, 0, FLOOR]) cylinder(d = SCREW_PIL, h = STANDOFF + 1);
  }
  // 蓋ネジの柱
  difference() {
    lug_positions() cylinder(d = LUG, h = FLOOR + INNER_Z);
    lug_positions() translate([0, 0, FLOOR + INNER_Z - 8])
      cylinder(d = SCREW_PIL, h = 9);
  }
}

// ── 蓋 ───────────────────────────────────────────────────
module lid() {
  difference() {
    union() {
      translate([-SHELL, -SHELL, 0])
        rrect(CASE_X, CASE_Y, LIDT, 2.5);
      /* 内側に落ちる縁。蓋を位置決めし、合わせ面のシリコンに迷路を作る。
       * **枠にすること。** 中実にすると基板上面（18.6mm）より下へ降りて
       * J1 の熱収縮（12mm）に当たる。 */
      LIP_T = 1.5;
      translate([0.3, 0.3, -1.2]) difference() {
        cube([INNER_X - 0.6, INNER_Y - 0.6, 1.2]);
        translate([LIP_T, LIP_T, -0.5])
          cube([INNER_X - 0.6 - 2*LIP_T, INNER_Y - 0.6 - 2*LIP_T, 2.2]);
      }
      // ケーブル出口の樋。溝に沿って縁まで伸ばし、シリコンのダムにする
      // 端は外形と面一にする（はみ出すと引っ掛かる）
      translate([0, CBL_CY, LIDT])
        hull() for (x = [CBL_CX + (CBL_W - CBL_L)/2, -SHELL + (CBL_L + 2*CBL_WALL)/2])
          translate([x, 0, 0]) cylinder(d = CBL_L + 2*CBL_WALL, h = CBL_BOSS);
    }
    // ケーブルの U 溝（樋ごと貫通し、-x の縁まで開く）
    translate([0, CBL_CY, -2])
      hull() for (x = [CBL_CX + (CBL_W - CBL_L)/2, -SHELL - 2])
        translate([x, 0, 0]) cylinder(d = CBL_L, h = LIDT + CBL_BOSS + 4);
    // 蓋のネジ穴（頭を落とす）
    lug_positions() {
      translate([0, 0, -1]) cylinder(d = SCREW_D + 0.4, h = LIDT + 2);
      translate([0, 0, LIDT - 1.4]) cylinder(d = SCREW_D + 2.6, h = 2);
    }
    // 縁が基板の取付穴の柱と当たらないよう逃がす
    hole_positions() translate([0, 0, -1.6]) cylinder(d = HOLE_D + 4.0, h = 2.0);
  }
}

// ── 出力 ─────────────────────────────────────────────────
PART = "both";   // "base" / "lid" / "both"

if (PART == "base" || PART == "both") base();
if (PART == "lid"  || PART == "both") translate([0, CASE_Y + 6, 0]) lid();
