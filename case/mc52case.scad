/* MC52 基板のケース（PETG で 3D プリント）
 *
 * 基板は ../hardware/。50 × 40mm、取付穴 φ2.8 が各辺から 3.5mm。
 * **探索＋記録フェーズ用の窓なし箱。** 表示器が未決なので窓は付けない。
 *
 * ── 実測（2026-09-15）────────────────────────────────────
 *   C2（電解）8mm / J1 の熱収縮 12mm / 線の曲がり始め 20mm / シース下端 33mm・外径 6mm
 *
 * **J1 の 12mm が内寸を支配する。** 線は蓋から真っ直ぐ抜いて外で曲げる
 * （中で曲げると内寸 22mm 以上になる）。
 *
 * ── 固定の考え方 ─────────────────────────────────────────
 * **ネジ 1 組で蓋・基板・本体をまとめて締める。**
 *
 *   蓋の柱（上から 13mm 降りる）→ 基板の取付穴（素通し）→ 本体の柱にタッピング
 *
 * 基板が上下の柱に挟まれるので、基板専用のネジが要らない。**蓋の固定点を基板の
 * 外へ出す必要も無く、外形は基板＋壁だけで済む。**
 *
 * **M2 を使う。** M2.5 の六角穴は逃げ半径 2.25mm を要求するが、取付穴から最寄り
 * 部品までは 左上 2.55 / 左下 2.72 / 右上 2.96 / 右下 7.67mm しかない
 * （hardware/README.md）。φ4.0 の柱（半径 2.0）なら 4 隅とも 0.55mm 以上空く。
 *
 * **蓋の柱は左下だけ省く。** そこは J1 の線が出る角で、ケーブルの U 溝と 0.2mm
 * 食い合う。3 点で十分留まるし、基板はその角も本体の柱に載る。
 */

// ── 基板 ─────────────────────────────────────────────────
PCB_X = 50.0; PCB_Y = 40.0; PCB_T = 1.6;
HOLE_IN = 3.5; HOLE_D = 2.8;
J1_X = 2.54; J1_Y = 7.62; J1_PITCH = 2.54;   // ../hardware/Net_List.enet

H_J1 = 12.0;   // 熱収縮の頂点。内寸を支配する
H_C2 = 8.0;

// ── ケース ───────────────────────────────────────────────
WALL  = 2.0;   // 0.4mm ノズルで 5 周
FLOOR = 2.5;   // タイラップ溝を彫っても 1.5mm 残る
LIDT  = 2.5;
CLR   = 0.4;   // 基板と内壁の片側隙間
STANDOFF = 3.0;   // 基板下の逃げ。J1 のピンが裏へ突き出る
HEAD     = 1.0;   // J1 頂点と蓋裏の隙間

// M2。柱 φ4.0 / 下穴 φ1.6（肉厚 1.2mm）/ 素通し φ2.2 / 皿 φ3.8
SCREW_PIL = 1.6; SCREW_CLR = 2.2; SCREW_HEAD = 3.8;
POST_D = 4.0;                // 蓋の柱。半径 2.0 < 最寄り部品 2.55mm
BOSS_D = HOLE_D + 2.0;       // 本体の柱 = 4.8

INNER_X = PCB_X + 2*CLR;
INNER_Y = PCB_Y + 2*CLR;
INNER_Z = STANDOFF + PCB_T + H_J1 + HEAD;
CASE_X  = INNER_X + 2*WALL;
CASE_Y  = INNER_Y + 2*WALL;

PCB_TOP = FLOOR + STANDOFF + PCB_T;   // 基板上面
LID_Z   = FLOOR + INNER_Z;            // 蓋の裏
POST_H  = LID_Z - PCB_TOP;            // 蓋の柱の長さ = 13.0

/* ケーブル出口。**縁まで開いた U 溝。**
 * 閉じた長穴だと蓋が入らない —— 線は既に J1 へハンダ付け済みで、蓋を上から通すには
 * ケーブルの反対端（4 ピンカプラ）を長穴に通す必要があるが、通らない。
 * 溝は線が一列に並んでいる x 方向へ抜く（幅で済み、y 方向より開口が小さい）。
 * **樋は付けない。** シリコンを塗らない方針になったので充填の深さが要らず、
 * 付けると蓋の柱と反対を向いて印刷でサポートが要る。 */
CBL_W = 8.4; CBL_L = 4.6;

/* タイラップ。**溝にして底を貫かない。** 壁が 2.0mm しかないのでトンネルは抜ける。
 * ケースの外周を一周させ、底と蓋の両方に溝を彫る。締めた帯が蓋を押さえる働きも兼ねる。 */
TIE_W = 5.0; TIE_D = 1.0;

$fn = 48;

function px(x) = x + CLR;
function py(y) = y + CLR;
CBL_CX = px(J1_X + J1_PITCH);
CBL_CY = py(J1_Y);

module rrect(x, y, z, r) {
  hull() for (a = [r, x - r], b = [r, y - r]) translate([a, b, 0]) cylinder(r = r, h = z);
}
// 取付穴 4 箇所（本体の柱）
module hole_positions() {
  for (x = [HOLE_IN, PCB_X - HOLE_IN], y = [HOLE_IN, PCB_Y - HOLE_IN])
    translate([px(x), py(y), 0]) children();
}
// 蓋の柱 3 箇所（左下 = ケーブルが出る角を省く）
module post_positions() {
  for (p = [[PCB_X - HOLE_IN, HOLE_IN], [HOLE_IN, PCB_Y - HOLE_IN], [PCB_X - HOLE_IN, PCB_Y - HOLE_IN]])
    translate([px(p[0]), py(p[1]), 0]) children();
}
module tie_cut(z) {
  for (y = [INNER_Y*0.28, INNER_Y*0.72])
    translate([-WALL - 1, y - TIE_W/2, z]) cube([CASE_X + 2, TIE_W, TIE_D + 0.02]);
}

// ── 本体 ─────────────────────────────────────────────────
module base() {
  difference() {
    translate([-WALL, -WALL, 0]) rrect(CASE_X, CASE_Y, FLOOR + INNER_Z, 2.0);
    translate([0, 0, FLOOR]) cube([INNER_X, INNER_Y, INNER_Z + 1]);   // キャビティ
    tie_cut(-0.01);
  }
  /* **基板を受ける柱はキャビティを彫った後に足す。**
   * difference の中で union すると、キャビティの立方体が柱ごと削ってしまう。 */
  difference() {
    hole_positions() cylinder(d = BOSS_D, h = FLOOR + STANDOFF);
    hole_positions() translate([0, 0, FLOOR - 1]) cylinder(d = SCREW_PIL, h = STANDOFF + 2);
  }
}

// ── 蓋（z=0 が外面。組み立て時は裏返して LID_Z へ）──────────
module lid() {
  LIP_T = 1.5;
  difference() {
    union() {
      translate([-WALL, -WALL, 0]) rrect(CASE_X, CASE_Y, LIDT, 2.0);
      /* 内側に落ちる縁。蓋を位置決めする。**枠にすること。**
       * 中実にすると基板上面より下へ降りて J1 の熱収縮に当たる。 */
      translate([0.3, 0.3, -1.2]) difference() {
        cube([INNER_X - 0.6, INNER_Y - 0.6, 1.2]);
        translate([LIP_T, LIP_T, -0.5])
          cube([INNER_X - 0.6 - 2*LIP_T, INNER_Y - 0.6 - 2*LIP_T, 2.2]);
      }
      // 基板まで降りる柱
      post_positions() translate([0, 0, -POST_H]) cylinder(d = POST_D, h = POST_H);
    }
    // U 溝（縁ごと貫通し、-x の縁まで開く）
    translate([0, CBL_CY, -POST_H - 2])
      hull() for (x = [CBL_CX + (CBL_W - CBL_L)/2, -WALL - 2])
        translate([x, 0, 0]) cylinder(d = CBL_L, h = POST_H + LIDT + 4);
    // ネジ（素通し＋皿）
    post_positions() {
      translate([0, 0, -POST_H - 1]) cylinder(d = SCREW_CLR, h = POST_H + LIDT + 2);
      translate([0, 0, LIDT - 1.2]) cylinder(d = SCREW_HEAD, h = 2);
    }
    tie_cut(LIDT - TIE_D);
  }
}

PART = "both";
if (PART == "base" || PART == "both") base();
if (PART == "lid"  || PART == "both") translate([0, CASE_Y + 6, 0]) lid();
