/* MC52 — Honda 独自層の探索
 *
 * **この基板が必要になった理由そのもの。** 標準 OBD 層（`obd` 環境）は ELM327 で
 * 既に取れているので、基板を起こした価値は「ELM327 では原理的に叩けない層」にある。
 * 越えるべき制約は 3 点あり、どれも GPIO と UART を直接握れば出せる。
 *
 *   起動      K 線を 70ms Low   … fast init は 25ms 固定で任意長ブレークを出せない
 *   フレーム  72 05 71 TT CS    … ELM327 は必ず 8N TA SA を前置する
 *   CS        総和の 2 の補数   … ISO 14230 は単純和
 *
 * **仕様の出所と、どこまで信用できるかは PROVENANCE.md。** 受領した仕様書の
 * 全フレームを自前で検算し、信用できる事実とできない事実を分けてある。
 * 実装はその判定に従う。
 *
 * **MC52 が独自層を喋ること自体が未検証。** ウェイクアップは CRF250L と CBR600RR で
 * 既に違っており、MC52 がどちらでもない可能性がある。だから決め打ちで 0xD1 を
 * 読むのではなく、ウェイクアップ 2 種を試し、テーブルを総当たりするところから入る。
 */
#include <Arduino.h>

static const int PIN_KL_TX = 17;
static const int PIN_KL_RX = 18;
static const uint32_t KL_BAUD = 10400;     // 両車種とも 10400 8N1
HardwareSerial KL(1);

/* フレーム全体の総和が 0 になるようにチェックサムを置く規則。
 * 送信側は CS = (-Σ先行バイト) mod 256、受信側は Σ全バイト == 0 で検証できる。
 * **この規則は受領した仕様書の要求フレーム 6 種すべてで検算が一致している。** */
static uint8_t csum(const uint8_t *b, size_t n) {
  uint8_t s = 0;
  for (size_t i = 0; i < n; i++) s -= b[i];
  return s;
}
static bool csOk(const uint8_t *b, size_t n) {
  uint8_t s = 0;
  for (size_t i = 0; i < n; i++) s += b[i];
  return s == 0;
}

static void dump(const char *tag, const uint8_t *b, size_t n) {
  Serial.print(tag);
  Serial.printf("[%2u]", (unsigned)n);
  for (size_t i = 0; i < n; i++) Serial.printf(" %02X", b[i]);
  Serial.println();
}

static void klRaw()  { KL.end(); pinMode(PIN_KL_TX, OUTPUT); }
static void klUart() { KL.begin(KL_BAUD, SERIAL_8N1, PIN_KL_RX, PIN_KL_TX); }

/* 送信 → 半二重のエコーを読み捨て → 応答を 1 フレーム受ける。
 * **応答の 2 バイト目が総バイト数**（仕様書・検算とも 16/16 で一致）。
 * 戻り値 >0 = 長さ / 0 = 無応答 / -1 = 途中で切れた / -2 = 長さが不正 / -3 = CS 不一致 */
static int xfer(const uint8_t *req, size_t n, uint8_t *resp, size_t cap, uint32_t wait_ms) {
  while (KL.available()) KL.read();
  KL.write(req, n);
  KL.flush();
  uint32_t t0 = millis();
  for (size_t i = 0; i < n && millis() - t0 < 300; ) if (KL.available()) { KL.read(); i++; }

  size_t got = 0, need = 0;
  t0 = millis();
  while (millis() - t0 < wait_ms) {
    if (!KL.available()) continue;
    uint8_t c = KL.read();
    if (got < cap) resp[got] = c;
    got++;
    if (got == 2) { need = c; if (need < 4 || need > cap) return -2; }
    if (need && got >= need) return csOk(resp, need) ? (int)need : -3;
    t0 = millis();                        // バイト間でタイムアウトを延長
  }
  return got ? -1 : 0;
}

/* テーブル要求 72 05 71 TT CS */
static int readTable(uint8_t table, uint8_t *resp, size_t cap, uint32_t wait_ms = 250) {
  uint8_t f[5] = {0x72, 0x05, 0x71, table, 0};
  f[4] = csum(f, 4);
  return xfer(f, 5, resp, cap, wait_ms);
}

static bool linked = false;
static uint32_t lastKeep = 0;

/* keep-alive。**CBR600RR はテーブル 0x00 の要求を約 2 秒周期で撃っている。**
 * 応答のバイト列は公開されていないので、応答の中身は見ない（来れば十分）。
 * MC52 で必要な周期は不明。2 秒で足りなければここを詰める。 */
static void keepAlive() {
  if (!linked || millis() - lastKeep < 2000) return;
  uint8_t r[64];
  readTable(0x00, r, sizeof r, 150);
  lastKeep = millis();
}

/* 初期化。**K 線を 70ms Low に落とすところが ELM327 にできない部分。**
 * ウェイクアップは車種で異なることが分かっているので両方試す。
 *   CRF250L  FE 04 72 8C
 *   CBR600RR FE 04 FF FF
 * 初期化フレームは両車種で共通 72 05 00 F0 99。
 *
 * **成功判定は緩くしてある。** CBR は 02 04 00 FA との完全一致、CRF は総和が
 * ある値になることを条件にしているが、**MC52 が何を返すかは未知**。ここで
 * 決め打ちすると「応答しているのに失敗と判定する」事故になるので、
 * **形式の整ったフレームが返れば成功**とし、中身は画面に出して人間が見る。 */
static bool propInit(bool verbose = true) {
  static const uint8_t WAKE_A[4] = {0xFE, 0x04, 0x72, 0x8C};   // CRF250L
  static const uint8_t WAKE_B[4] = {0xFE, 0x04, 0xFF, 0xFF};   // CBR600RR
  static const uint8_t INIT[5]   = {0x72, 0x05, 0x00, 0xF0, 0x99};
  uint8_t resp[64];

  for (int v = 0; v < 2; v++) {
    const uint8_t *wake = v ? WAKE_B : WAKE_A;
    if (verbose) Serial.printf("ウェイクアップ %s（%s 系）\n",
                               v ? "FE 04 FF FF" : "FE 04 72 8C", v ? "CBR600RR" : "CRF250L");
    klRaw();
    digitalWrite(PIN_KL_TX, HIGH); delay(200);
    digitalWrite(PIN_KL_TX, LOW);  delay(70);     // ★ ELM327 が出せない 70ms ブレーク
    digitalWrite(PIN_KL_TX, HIGH); delay(120);
    klUart();

    int r = xfer(wake, 4, resp, sizeof resp, 300);
    if (verbose && r > 0) dump("  wake 応答 ", resp, r);
    delay(200);                                    // ウェイクアップ → 初期化は 200ms

    r = xfer(INIT, 5, resp, sizeof resp, 400);     // 応答は 50ms 前後で返る
    if (r > 0) {
      if (verbose) {
        dump("  init 応答 ", resp, r);
        // 参考: CBR600RR はこの 4 バイトとの完全一致を成功条件にしている
        if (r == 4 && resp[0] == 0x02 && resp[1] == 0x04 && resp[2] == 0x00)
          Serial.println("  （CBR600RR と同じ 02 04 00 FA）");
      }
      Serial.printf("  **独自層が応答した**（ウェイクアップ %s）\n", v ? "B" : "A");
      lastKeep = millis();
      return true;
    }
    if (verbose) Serial.printf("  %s\n", r == 0 ? "無応答" : r == -3 ? "CS 不一致" : "応答が壊れている");
  }
  return false;
}

/* ── テーブル総当たり ─────────────────────────────────────
 * **MC52 で最初にやること。** 公開されている範囲で応答が確認できているのは
 * 0x00 0x10 0x11 0x20 0x61 0x70 0xD0 0xD1 の 8 つだけだが、これは
 * 「ECU がこの 8 種類しか持たない」という意味ではない。
 * **未対応テーブルに ECU が何を返すか（無応答か・エラーか・空か）も不明。** */
static void cmdScan() {
  if (!linked) { Serial.println("先に 'w' で初期化する"); return; }
  Serial.println("-- テーブル総当たり 0x00〜0xFF --");
  uint8_t resp[160];
  int okN = 0, csN = 0;
  for (int t = 0; t <= 0xFF; t++) {
    keepAlive();
    int r = readTable((uint8_t)t, resp, sizeof resp, 200);
    if (r > 0) {
      okN++;
      Serial.printf("  %02X 長%2d :", t, r);
      for (int i = 0; i < r && i < 26; i++) Serial.printf(" %02X", resp[i]);
      Serial.println(r > 26 ? " …" : "");
    } else if (r == -3) { csN++; Serial.printf("  %02X 応答あり・CS 不一致\n", t); }
    else if (r == -2)   { csN++; Serial.printf("  %02X 応答あり・長さが不正\n", t); }
    delay(30);
  }
  Serial.printf("応答 %d / CS か長さが不正 %d / 無応答 %d\n", okN, csN, 256 - okN - csN);
  if (!okN && !csN)
    Serial.println("**1 つも応答しない。MC52 は独自層を喋らないか、ウェイクアップが違う**");
}

/* ── 0xD1 = 状態 ─────────────────────────────────────────
 * **index 4 が噛み合い状態。** 位置は 2 系統で裏が取れている ——
 * CBR600RR の例が index 4 を Gear status とし、CRF250L の実測（先頭補正後
 * 02 0B 71 D1 **03** …）が index 4 に 0x03 = サイドスタンドを持つ。
 * **値の対応（00/01/03）は CBR 側の記述のみ。MC52 では未検証。**
 * CRF 側は別実装と食い違いがあり確定仕様にできない、と収集元も留保している。 */
static void showD1(const uint8_t *r, int n) {
  if (n < 6) { Serial.println("  短すぎて解釈しない"); return; }
  uint8_t s = r[4];
  const char *m = s == 0x00 ? "イン（段が入っている）"
                : s == 0x01 ? "ニュートラルまたはクラッチ"
                : s == 0x03 ? "サイドスタンド" : "**未知の値**";
  Serial.printf("  index4 = 0x%02X  %s\n", s, m);
  Serial.print("  残り :");
  for (int i = 5; i < n - 1; i++) Serial.printf(" [%d]=%02X", i, r[i]);
  Serial.println("   ← 意味は未知。走行中に変化するものを探す");
}

/* ── 0x10 / 0x11 = センサ群 ──────────────────────────────
 * 配置は CBR600RR の 0x10 と CRF250L の 0x11 で一致している。
 * **CBR 側の例はチェックサムが合わないのでバイト値は採用せず、位置だけ使う。**
 * 換算式は CBR 側の実装から。**MC52 では未検証。**
 *
 * **噴射時間は index 18-19。** CRF250L の実測記録がそこを Fuel Inj としている。
 * ただし単位・endian・スケール・本当に開弁時間なのかは**すべて不明**。
 * 標準層に存在しない量なので、ここが取れるかが基板を起こした意味に直結する。 */
static void showSensors(const uint8_t *r, int n) {
  auto v = [&](int i) { return i < n ? r[i] : 0; };
  if (n < 20) { Serial.printf("  長さ %d。先行事例の配置（20 以上）に満たないので解釈しない\n", n); return; }
  Serial.printf("  RPM   [4-5]   %u\n", (v(4) << 8) | v(5));
  Serial.printf("  TPS   [6-7]   %.2f V / %.1f %%\n", v(6) * 5.0 / 256, v(7) / 16.0 * 10);
  Serial.printf("  ECT   [8-9]   %.2f V / %d ℃\n", v(8) * 5.0 / 256, (int)v(9) - 40);
  Serial.printf("  IAT   [10-11] %.2f V / %d ℃\n", v(10) * 5.0 / 256, (int)v(11) - 40);
  Serial.printf("  MAP   [12-13] %.2f V / %u kPa\n", v(12) * 5.0 / 256, v(13));
  Serial.printf("  電圧  [16]    %.1f V\n", v(16) / 10.0);
  Serial.printf("  車速  [17]    %u km/h\n", v(17));
  Serial.printf("  噴射? [18-19] %02X %02X （BE:%u LE:%u）**単位もスケールも不明**\n",
                v(18), v(19), (v(18) << 8) | v(19), (v(19) << 8) | v(18));
  Serial.print("  未知 :");
  for (int i : {14, 15}) Serial.printf(" [%d]=%02X", i, v(i));
  for (int i = 20; i < n - 1; i++) Serial.printf(" [%d]=%02X", i, v(i));
  Serial.println();
}

static void cmdTable(uint8_t t, bool poll) {
  if (!linked) { Serial.println("先に 'w' で初期化する"); return; }
  uint8_t resp[160];
  for (;;) {
    keepAlive();
    int r = readTable(t, resp, sizeof resp);
    if (r <= 0) Serial.printf("%02X 応答なし (%d)\n", t, r);
    else {
      dump("", resp, r);
      if (t == 0xD1) showD1(resp, r);
      if (t == 0x10 || t == 0x11 || t == 0x61) showSensors(resp, r);
    }
    if (!poll) return;
    delay(300);
    if (Serial.available()) { while (Serial.available()) Serial.read(); return; }
  }
}

static void help() {
  Serial.println();
  Serial.println("== MC52 Honda 独自層 探索 ==");
  Serial.println("  w    初期化（70ms ブレーク → ウェイクアップ 2 種 → 72 05 00 F0 99）");
  Serial.println("  s    テーブル 0x00〜0xFF 総当たり  ★ MC52 で最初にやること");
  Serial.println("  d    0xD1（index4 = 噛み合い状態。比推定に欠けていた入力）");
  Serial.println("  m    0x11 / 0x10（センサ群。index18-19 が噴射時間か）");
  Serial.println("  tXX  テーブル XX を 1 回   pXX  連続ポーリング（任意のキーで停止）");
  Serial.println("  h    この一覧");
  Serial.println("出所と信頼度は PROVENANCE.md。**MC52 では全部未検証。**");
}

static int hex2() {
  uint32_t t0 = millis();
  int v = 0, got = 0;
  while (got < 2 && millis() - t0 < 3000) {
    if (!Serial.available()) continue;
    int c = Serial.read();
    int d = (c >= '0' && c <= '9') ? c - '0'
          : (c >= 'a' && c <= 'f') ? c - 'a' + 10
          : (c >= 'A' && c <= 'F') ? c - 'A' + 10 : -1;
    if (d >= 0) { v = v * 16 + d; got++; }
  }
  return got == 2 ? v : -1;
}

void setup() {
  Serial.begin(115200);
  delay(400);
  klRaw();
  digitalWrite(PIN_KL_TX, HIGH);
  klUart();
  help();
}

void loop() {
  keepAlive();
  if (!Serial.available()) return;
  int c = Serial.read();
  switch (c) {
    case 'w': linked = propInit(); Serial.println(linked ? "リンク確立" : "**全滅**"); break;
    case 's': cmdScan(); break;
    case 'd': cmdTable(0xD1, false); break;
    case 'm': cmdTable(0x11, false); cmdTable(0x10, false); break;
    case 't': { int t = hex2(); if (t >= 0) cmdTable((uint8_t)t, false); else Serial.println("t の後に 16 進 2 桁"); break; }
    case 'p': { int t = hex2(); if (t >= 0) cmdTable((uint8_t)t, true);  else Serial.println("p の後に 16 進 2 桁"); break; }
    case 'h': help(); break;
    default: return;
  }
  Serial.println();
}
