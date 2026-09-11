/* MC52（CB250R 2018）K-Line ブリングアップ
 *
 * **目的は 1 つ。L9637D が VCC = 3.3V で K ラインを通すかを判定する。**
 * データシートの動作電圧範囲は 3〜7V で全範囲が設計保証だが、試験条件は 5V のみ。
 * 基板上でここだけが机上で終わっていない（hardware/README.md）。
 *
 * 判定は 2 段階で出る。
 *   1. **自分の送信がエコーで返る** … K ラインは単線半二重なので、TX した波形が
 *      そのまま RX に戻る。これが正しく返れば TX→K→RX の往復が 3.3V で成立している。
 *      車両が応答しなくてもここまでは分かる
 *   2. **ECU が応答する** … 相手が居る。ここまで来れば標準 OBD 層は使える
 *
 * 通信仕様は Track A（ELM327）の実測から（FINDINGS.md「通信の同定」）。
 *   ISO 14230-4 KWP FAST / 10400bps / テスタ 0xF1 / ECU 0x10 / 応答ヘッダ 8N F1 10
 *
 * **独自層には触れない。** あちらは CB250R で喋るかどうか自体が未検証なので、
 * 先に標準層を通してファームのバグと車両の未知を切り分ける足場を作る。
 */
#include <Arduino.h>

// ── ピン（hardware/Net_List.enet と一致） ──────────────────
static const int PIN_KL_TX = 17;   // U3.4 (TX in)   UART1 既定
static const int PIN_KL_RX = 18;   // U3.1 (RX out)  UART1 既定

static const uint32_t KL_BAUD = 10400;
static const uint8_t  ADDR_TESTER = 0xF1;
static const uint8_t  ADDR_ECU    = 0x10;
static const uint8_t  ADDR_FUNC   = 0x33;   // 機能アドレス（OBD 要求先）

/* ISO 14230-2 のタイミング。P2 は ECU の応答開始まで、P3 は要求どうしの間隔。
 * Track A の実測で 1 周期 730ms・欠測 2〜3% が出ているので、ここも余裕を持たせる。 */
static const uint32_t P2_MAX_MS = 120;   // 規格は 50ms だが取りこぼしを避けて広めに
static const uint32_t P3_MIN_MS = 60;    // 規格 55ms

HardwareSerial KL(1);

static uint8_t checksum(const uint8_t *b, size_t n) {
  uint8_t s = 0;
  for (size_t i = 0; i < n; i++) s += b[i];
  return s;
}

static void hexdump(const char *tag, const uint8_t *b, size_t n) {
  Serial.printf("%s [%u]", tag, (unsigned)n);
  for (size_t i = 0; i < n; i++) Serial.printf(" %02X", b[i]);
  Serial.println();
}

/* 送信したぶんをエコーとして読み捨てる。**戻ってきたバイトが送ったものと
 * 一致するかを見る**ことが、そのまま 3.3V 動作の判定になる。 */
static bool drainEcho(const uint8_t *sent, size_t n) {
  uint32_t t0 = millis();
  size_t i = 0;
  bool ok = true;
  while (i < n && millis() - t0 < 200) {
    if (!KL.available()) { delay(1); continue; }
    uint8_t c = KL.read();
    if (c != sent[i]) ok = false;
    i++;
  }
  if (i < n) { Serial.printf("  エコーが %u/%u バイトしか返らない\n", (unsigned)i, (unsigned)n); return false; }
  if (!ok)    { Serial.println("  エコーの内容が送信と一致しない"); return false; }
  return true;
}

/* 応答を 1 フレーム読む。形式バイト 0x8N の下位 6bit がヘッダ以降のデータ長。
 * ELM327 と違い生バイトなので、チェックサムも自分で検算する。 */
static int readFrame(uint8_t *buf, size_t cap, uint32_t timeout) {
  uint32_t t0 = millis();
  size_t got = 0, need = 0;
  while (millis() - t0 < timeout) {
    if (!KL.available()) { delay(1); continue; }
    uint8_t c = KL.read();
    if (got == 0 && (c & 0xC0) != 0x80) continue;      // 形式バイトを待つ
    if (got < cap) buf[got] = c;
    got++;
    if (got == 1) need = 1 + 2 + (c & 0x3F) + 1;       // fmt + addr2 + data + cs
    if (need && got >= need) break;
    t0 = millis();                                     // バイト間はタイムアウトを延長
  }
  if (!need || got < need) return -1;
  if (checksum(buf, need - 1) != buf[need - 1]) {
    Serial.println("  チェックサム不一致");
    return -2;
  }
  return (int)need;
}

static bool sendAndRead(const uint8_t *req, size_t n, uint8_t *resp, size_t cap, int *rlen) {
  while (KL.available()) KL.read();
  KL.write(req, n);
  KL.flush();
  if (!drainEcho(req, n)) return false;
  *rlen = readFrame(resp, cap, P2_MAX_MS);
  return *rlen > 0;
}

/* ISO 14230-4 fast init。25ms Low → 25ms High のウェイクアップの後、
 * StartCommunication（サービス 0x81）を投げる。 */
static bool fastInit() {
  KL.end();
  pinMode(PIN_KL_TX, OUTPUT);
  digitalWrite(PIN_KL_TX, HIGH);
  delay(300);                      // W5: バスのアイドルを確保
  digitalWrite(PIN_KL_TX, LOW);  delay(25);
  digitalWrite(PIN_KL_TX, HIGH); delay(25);
  KL.begin(KL_BAUD, SERIAL_8N1, PIN_KL_RX, PIN_KL_TX);

  uint8_t req[5] = {0xC1, ADDR_FUNC, ADDR_TESTER, 0x81, 0};
  req[4] = checksum(req, 4);
  uint8_t resp[16];
  int n;
  Serial.println("fast init …");
  hexdump("  送信", req, 5);
  if (!sendAndRead(req, 5, resp, sizeof resp, &n)) {
    Serial.println("  **応答なし。** エコーが返っていれば L9637D は 3.3V で動作している");
    return false;
  }
  hexdump("  受信", resp, n);
  // 肯定応答は 0xC1（StartCommunication + 0x40）＋キーバイト 2 個
  return n >= 6 && resp[3] == 0xC1;
}

/* サービス 01 の PID を 1 つ読む。要求は機能アドレス宛て。 */
static int readPid(uint8_t pid, uint8_t *data, size_t cap) {
  uint8_t req[6] = {0xC2, ADDR_FUNC, ADDR_TESTER, 0x01, pid, 0};
  req[5] = checksum(req, 5);
  uint8_t resp[32];
  int n;
  if (!sendAndRead(req, 6, resp, sizeof resp, &n)) return -1;
  // 応答 8N F1 10 41 <pid> <data...> <cs>
  if (n < 7 || resp[1] != ADDR_TESTER || resp[2] != ADDR_ECU
      || resp[3] != 0x41 || resp[4] != pid) { hexdump("  想定外", resp, n); return -1; }
  int dlen = (resp[0] & 0x3F) - 2;
  if (dlen < 0 || (size_t)dlen > cap) return -1;
  memcpy(data, resp + 5, dlen);
  return dlen;
}

static bool linked = false;

void setup() {
  Serial.begin(115200);
  delay(400);
  Serial.println();
  Serial.println("== MC52 K-Line ブリングアップ ==");
  Serial.printf("KL_TX=IO%d  KL_RX=IO%d  %lu bps\n", PIN_KL_TX, PIN_KL_RX, (unsigned long)KL_BAUD);
  Serial.println("エコーが一致すれば L9637D は 3.3V で K ラインを駆動できている");
  linked = fastInit();
  Serial.println(linked ? "リンク確立" : "リンク未確立。5 秒ごとに再試行する");
}

void loop() {
  static uint32_t lastRetry = 0;
  if (!linked) {
    if (millis() - lastRetry > 5000) { lastRetry = millis(); linked = fastInit(); }
    return;
  }
  uint8_t d[8];
  int n = readPid(0x0C, d, sizeof d);          // 回転数
  int rpm = (n == 2) ? ((d[0] << 8 | d[1]) / 4) : -1;
  delay(P3_MIN_MS);
  n = readPid(0x0D, d, sizeof d);              // 車速
  int kmh = (n == 1) ? d[0] : -1;
  delay(P3_MIN_MS);

  if (rpm < 0 && kmh < 0) {
    Serial.println("応答が途絶えた。再初期化する");
    linked = false;
    return;
  }
  Serial.printf("rpm %5d   speed %3d km/h\n", rpm, kmh);
}
