/* MC52 — K ライン探索コンソール（BLE / シリアル両対応）
 *
 * **探索フェーズ用。停車・エンジン掛けで使う。**
 *
 * 設計の要は「**書き換え回数を最小にする**」こと。いま分かっていないことが多すぎて、
 * 決め打ちの手順を並べたファームだと仮説が外れるたびに焼き直しになる。
 *
 *   ウェイクアップが CRF 系か CBR 系か、どちらでもないか
 *   初期化フレームが同じか / keep-alive の中身（仕様に記載が無い）
 *   テーブル番号の実在範囲 / 未対応テーブルの応答
 *   ブレーク長が本当に 70ms か
 *
 * そこで**任意のバイト列と任意長ブレークを Mac 側から投げられる**ようにしてある。
 * 便利コマンド（o / w / s / d / m）はその上に乗せた薄い層でしかない。
 *
 * **コマンドは BLE から入る。** バイクの横でノート PC を J3 に繋ぎたくないため。
 * シリアルも同じパーサを共有していて、BLE が死んだときの逃げ道になる。
 *
 * 仕様の出所と信頼度は PROVENANCE.md / KLINE_PROPRIETARY.md。**MC52 では全部未検証。**
 */
#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <time.h>
#include <WiFi.h>
#include <ArduinoOTA.h>
#include <WiFiMulti.h>
#include <Preferences.h>
#include <LittleFS.h>

static const int PIN_KL_TX = 17;
static const int PIN_KL_RX = 18;
static uint32_t klBaud = 10400;
HardwareSerial KL(1);

// ── 出力（シリアルと BLE の両方へ） ──────────────────────
static const char *SVC_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";
static const char *RX_UUID  = "6e400002-b5a3-f393-e0a9-e50e24dcca9e";  // Mac → 基板
static const char *TX_UUID  = "6e400003-b5a3-f393-e0a9-e50e24dcca9e";  // 基板 → Mac
static BLECharacteristic *txChar = nullptr;
static volatile bool bleConn = false;

static void out(const char *s) {
  Serial.print(s);
  if (!bleConn || !txChar) return;
  // notify の 1 回の上限に収まるよう刻む。詰めすぎるとスタックが詰まるので少し待つ
  const size_t CH = 180;
  for (size_t i = 0; s[i]; ) {
    size_t n = strnlen(s + i, CH);
    txChar->setValue((uint8_t *)(s + i), n);
    txChar->notify();
    i += n;
    delay(6);
  }
}
static void outf(const char *fmt, ...) {
  char b[512];
  va_list ap; va_start(ap, fmt); vsnprintf(b, sizeof b, fmt, ap); va_end(ap);
  out(b);
}
static void dump(const char *tag, const uint8_t *b, size_t n) {
  char line[600]; int p = snprintf(line, sizeof line, "%s[%2u]", tag, (unsigned)n);
  for (size_t i = 0; i < n && p < (int)sizeof line - 4; i++)
    p += snprintf(line + p, sizeof line - p, " %02X", b[i]);
  snprintf(line + p, sizeof line - p, "\n");
  out(line);
}

// ── K ラインの土台 ───────────────────────────────────────
/* 独自層のチェックサムは**総和の 2 の補数**（ISO 14230 の単純和とは別物）。
 * 受信側は全バイトの総和が 0 になることで検証できる。 */
static uint8_t csum2c(const uint8_t *b, size_t n) { uint8_t s = 0; for (size_t i = 0; i < n; i++) s -= b[i]; return s; }
static bool csOk2c(const uint8_t *b, size_t n)    { uint8_t s = 0; for (size_t i = 0; i < n; i++) s += b[i]; return s == 0; }
/* 標準 OBD 層（ISO 14230）は単純和。 */
static uint8_t csumAdd(const uint8_t *b, size_t n){ uint8_t s = 0; for (size_t i = 0; i < n; i++) s += b[i]; return s; }

// 記録は下で定義するが、xfer から呼ぶので前方宣言する
static const uint8_t T_PROP = 0x01, T_OBD = 0x02, T_REQ = 0x03, T_NOTE = 0x10;
static void logRec(uint8_t type, const uint8_t *d, size_t n);

static void klRaw()  { KL.end(); pinMode(PIN_KL_TX, OUTPUT); }
static void klUart() { KL.begin(klBaud, SERIAL_8N1, PIN_KL_RX, PIN_KL_TX); }

/* **K 線を任意の長さ Low に落とす。** ELM327 にできない部分そのもの
 * （fast init は 25ms 固定で、独自層が要求する 70ms を出せない）。 */
static void klBreak(uint32_t lowMs, uint32_t highMs) {
  klRaw();
  digitalWrite(PIN_KL_TX, HIGH); delay(200);
  digitalWrite(PIN_KL_TX, LOW);  delay(lowMs);
  digitalWrite(PIN_KL_TX, HIGH); delay(highMs);
  klUart();
}

/* 送信 → 半二重のエコーを捨てる → 応答を受ける。
 * `lenAt2` = 2 バイト目が総バイト数（独自層）。false なら長さを見ずに静かになるまで読む。 */
/* **エコーは捨てずに検証する。** K ラインは単線半二重なので送信波形がそのまま
 * RX に戻る。これが一致するかどうかが、そのまま物理層の健全性の指標になる
 * （配線の入れ違い、GND や 12V への短絡、L9637D の不調が全部ここに出る）。
 * 車両の前で「通信が通らない」となったとき、基板側か車両側かを切り分けられる。 */
static int echoBad = 0, echoGot = 0;
static int xfer(const uint8_t *req, size_t n, uint8_t *resp, size_t cap,
                uint32_t wait_ms, bool lenAt2) {
  while (KL.available()) KL.read();
  logRec(T_REQ, req, n);            // **要求も残す。** 何を訊いたかが対で要る
  KL.write(req, n); KL.flush();
  uint32_t t0 = millis();
  echoBad = 0; echoGot = 0;
  for (size_t i = 0; i < n && millis() - t0 < 400; ) {
    if (!KL.available()) continue;
    if (KL.read() != req[i]) echoBad++;
    i++; echoGot++;
  }

  size_t got = 0, need = 0;
  t0 = millis();
  while (millis() - t0 < wait_ms) {
    if (!KL.available()) { delay(1); continue; }
    uint8_t c = KL.read();
    if (got < cap) resp[got] = c;
    got++;
    if (lenAt2 && got == 2) { need = c; if (need < 3 || need > cap) return -2; }
    if (need && got >= need) { logRec(lenAt2 ? T_PROP : T_OBD, resp, need); return (int)need; }
    t0 = millis();
  }
  if (got) logRec(lenAt2 ? T_PROP : T_OBD, resp, got > cap ? cap : got);
  return got ? (int)got : 0;           // 長さ不明のときは静かになった時点の全量
}

// ── 状態 ─────────────────────────────────────────────────
static bool keepOn = false;
static uint32_t lastKeep = 0;
static uint8_t keepFrame[8] = {0x72, 0x05, 0x71, 0x00, 0x18};  // CBR600RR はテーブル 0x00 を約 2 秒周期
static size_t keepLen = 5;
static uint32_t keepMs = 2000;

static void keepAlive() {
  if (!keepOn || millis() - lastKeep < keepMs) return;
  uint8_t r[64];
  xfer(keepFrame, keepLen, r, sizeof r, 150, true);
  lastKeep = millis();
}

// ── 便利コマンド ─────────────────────────────────────────
static int readTable(uint8_t t, uint8_t *resp, size_t cap, uint32_t wait = 250) {
  uint8_t f[5] = {0x72, 0x05, 0x71, t, 0};
  f[4] = csum2c(f, 4);
  return xfer(f, 5, resp, cap, wait, true);
}

static void cmdPropInit() {
  static const uint8_t WA[4] = {0xFE, 0x04, 0x72, 0x8C};   // CRF250L
  static const uint8_t WB[4] = {0xFE, 0x04, 0xFF, 0xFF};   // CBR600RR
  static const uint8_t IN[5] = {0x72, 0x05, 0x00, 0xF0, 0x99};
  uint8_t r[64];
  for (int v = 0; v < 2; v++) {
    outf("ウェイクアップ %s（%s 系）\n", v ? "FE 04 FF FF" : "FE 04 72 8C", v ? "CBR600RR" : "CRF250L");
    klBreak(70, 120);
    int n = xfer(v ? WB : WA, 4, r, sizeof r, 300, false);
    if (n > 0) dump("  wake 応答 ", r, n);
    delay(200);
    n = xfer(IN, 5, r, sizeof r, 400, true);
    if (n > 0) {
      dump("  init 応答 ", r, n);
      outf("  **独自層が応答した**（ウェイクアップ %s）%s\n", v ? "B" : "A",
           csOk2c(r, n) ? "" : "  ※ CS 不一致");
      keepOn = true; lastKeep = millis();
      return;
    }
    outf("  無応答\n");
  }
  out("**両方とも応答なし**\n");
}

static void cmdScan() {
  out("-- テーブル総当たり 0x00〜0xFF --\n");
  uint8_t r[160];
  int ok = 0;
  for (int t = 0; t <= 0xFF; t++) {
    keepAlive();
    int n = readTable((uint8_t)t, r, sizeof r, 200);
    if (n > 0) {
      ok++;
      char tag[16]; snprintf(tag, sizeof tag, "  %02X %s", t, csOk2c(r, n) ? "  " : "★ ");
      dump(tag, r, n);
    }
    delay(25);
  }
  outf("応答 %d / 256（★ = チェックサム不一致）\n", ok);
  if (!ok) out("**1 つも応答しない。喋らないか、ウェイクアップが違う**\n");
}

/* 0xD1 の index 4 が噛み合い状態。位置は 2 系統で裏が取れているが、
 * **値の対応は CBR600RR 側の記述のみで MC52 では未検証。**
 * ギヤを入れてクラッチを握った状態で 0x01 を返すかどうかが、比推定の
 * クラッチ切り誤判定を潰せるかの分かれ目になる。 */
static void showD1(const uint8_t *r, int n) {
  if (n < 6) { out("  短すぎる\n"); return; }
  uint8_t s = r[4];
  outf("  index4 = 0x%02X  %s\n", s,
       s == 0x00 ? "イン（段が入っている）" : s == 0x01 ? "ニュートラルまたはクラッチ"
     : s == 0x03 ? "サイドスタンド" : "**未知の値**");
  char b[256]; int p = snprintf(b, sizeof b, "  他 :");
  for (int i = 5; i < n - 1 && p < (int)sizeof b - 12; i++) p += snprintf(b + p, sizeof b - p, " [%d]=%02X", i, r[i]);
  snprintf(b + p, sizeof b - p, "\n"); out(b);
}

/* 0x10 / 0x11 のセンサ群。**噴射時間は index 18-19**（CRF250L の実測記録）。
 * 単位・endian・スケールは不明なので両方の解釈を出す。
 * 停車でも空吹かしで動くので、位置と桁はここで取れる。 */
static void showSensors(const uint8_t *r, int n) {
  auto v = [&](int i) { return i < n ? r[i] : 0; };
  if (n < 20) { outf("  長さ %d。先行事例の配置に満たない\n", n); return; }
  outf("  RPM   [4-5]   %u\n", (v(4) << 8) | v(5));
  outf("  TPS   [6-7]   %.2f V / %.1f %%\n", v(6) * 5.0 / 256, v(7) / 16.0 * 10);
  outf("  ECT   [8-9]   %.2f V / %d C\n", v(8) * 5.0 / 256, (int)v(9) - 40);
  outf("  IAT   [10-11] %.2f V / %d C\n", v(10) * 5.0 / 256, (int)v(11) - 40);
  outf("  MAP   [12-13] %.2f V / %u kPa\n", v(12) * 5.0 / 256, v(13));
  outf("  電圧  [16]    %.1f V\n", v(16) / 10.0);
  outf("  車速  [17]    %u km/h\n", v(17));
  outf("  噴射? [18-19] %02X %02X （BE %u / LE %u）**単位もスケールも不明**\n",
       v(18), v(19), (v(18) << 8) | v(19), (v(19) << 8) | v(18));
}

static void cmdTable(uint8_t t) {
  uint8_t r[160];
  keepAlive();
  int n = readTable(t, r, sizeof r);
  if (n <= 0) { outf("%02X 応答なし\n", t); return; }
  dump("", r, n);
  if (!csOk2c(r, n)) out("  ※ チェックサム不一致\n");
  if (t == 0xD1) showD1(r, n);
  if (t == 0x10 || t == 0x11 || t == 0x61) showSensors(r, n);
}

// 16 進の切り出しは下で定義するが、poll の引数解釈で使うので前方宣言する
static int hexBytes(const char *s, uint8_t *b, size_t cap);

/* ── 実時間ストリーム ─────────────────────────────────────
 * **生バイトをそのまま押し出す。解釈しない。**
 *
 * バイト同定に必要なのはスナップショットではなく時系列。クラッチを握る瞬間や
 * スロットルを煽った瞬間に**どのバイトが動くか**を見る計器が要る。`d` や `m` の
 * 連打では取れない。
 *
 * 解釈を含まないので、先行事例のインデックスが MC52 で外れていてもこの層は
 * 間違いにならず、実用フェーズの送信経路としてそのまま使える。
 *
 * 行形式は機械可読に固定する（人向けの日本語出力とは混ぜない）。
 *
 *   P <経過ms> <TT> <hex..>     応答
 *   P <経過ms> <TT> -           無応答
 *
 * 律速は K ライン 10400bps。要求 5B ＋ 応答 30B ＋ ECU の間で 1 テーブル
 * 60〜85ms、3 本で 4〜5Hz が天井。周期が足りなければ詰めずに回す。
 *
 * **BLE が切れても止めない。** 走行中はスマホ非接続で `rec` の記録だけが走る。
 * `xfer()` が要求と応答を両方 logRec するので、記録側の改造は要らない。 */
static uint8_t pollTbl[8];
static int pollN = 0;
static uint32_t pollMs = 200, pollLast = 0, pollT0 = 0, pollCycles = 0;

static void pollTick() {
  if (!pollN || millis() - pollLast < pollMs) return;
  pollLast = millis();                 // 周期はサイクル開始基準（間隔ではなくレート）
  uint8_t r[160];
  char line[600];
  for (int i = 0; i < pollN; i++) {
    int n = readTable(pollTbl[i], r, sizeof r, 200);
    int p = snprintf(line, sizeof line, "P %lu %02X",
                     (unsigned long)(millis() - pollT0), pollTbl[i]);
    if (n <= 0) p += snprintf(line + p, sizeof line - p, " -");
    else for (int k = 0; k < n && p < (int)sizeof line - 4; k++)
      p += snprintf(line + p, sizeof line - p, " %02X", r[k]);
    snprintf(line + p, sizeof line - p, "\n");
    out(line);
  }
  pollCycles++;
  lastKeep = millis();   // 通信自体がセッションを維持する。keep-alive は要らない
}

static void cmdPoll(char *arg) {
  if (!strncmp(arg, "off", 3)) {
    if (!pollN) { out("停止中\n"); return; }
    outf("停止（%lu 周期 / %lu 秒）\n", (unsigned long)pollCycles,
         (unsigned long)((millis() - pollT0) / 1000));
    pollN = 0;
    return;
  }
  if (!*arg) {
    if (!pollN) { out("停止中。poll <テーブル..> [周期ms]   例: poll D1 11 200\n"); return; }
    char b[128]; int p = snprintf(b, sizeof b, "%lu ms 周期で", (unsigned long)pollMs);
    for (int i = 0; i < pollN; i++) p += snprintf(b + p, sizeof b - p, " %02X", pollTbl[i]);
    outf("%s（%lu 周期）\n", b, (unsigned long)pollCycles);
    return;
  }
  /* **2 桁までをテーブル、3 桁以上を周期 ms と解釈する。** hexBytes は非 16 進を
   * 読み飛ばすので "D1 11 200" を D1 11 20 00 と読んでしまう。ここは自前で切る。 */
  uint8_t tb[8]; int tn = 0; uint32_t iv = pollMs;
  for (char *s = arg; *s; ) {
    while (*s == ' ') s++;
    if (!*s) break;
    char *e = s; while (*e && *e != ' ') e++;
    char tok[16]; size_t len = (size_t)(e - s);
    if (len > sizeof tok - 1) len = sizeof tok - 1;
    memcpy(tok, s, len); tok[len] = 0;
    if (len <= 2) { uint8_t v; if (hexBytes(tok, &v, 1) == 1 && tn < 8) tb[tn++] = v; }
    else iv = strtoul(tok, nullptr, 10);
    s = e;
  }
  if (!tn) { out("テーブルを 16 進 2 桁で。例: poll D1 11 200\n"); return; }
  if (iv < 20) iv = 20;
  if (iv > 60000) iv = 60000;
  memcpy(pollTbl, tb, tn); pollN = tn; pollMs = iv;
  pollT0 = pollLast = millis(); pollCycles = 0;
  char b[128]; int p = 0;
  for (int i = 0; i < tn; i++) p += snprintf(b + p, sizeof b - p, " %02X", tb[i]);
  outf("開始:%s を %lu ms 周期（1 テーブル 60〜85ms なので %d 本だと実効 %lu ms 程度）\n",
       b, (unsigned long)iv, tn, (unsigned long)(iv > (uint32_t)tn * 75 ? iv : (uint32_t)tn * 75));
  if (!keepOn) out("※ `w` で独自層を起こしていない。無応答が続くなら先に w\n");
}

/* 標準 OBD 層。ELM327 で既に取れているものの再現で、**足場**。
 * ここが通れば UART・タイミング・エコー処理が正しいと分かり、独自層が
 * 無反応だったときに「実装が悪いのか MC52 が喋らないのか」を切り分けられる。 */
/* K ライン折り返し。**車両に繋がずに物理層だけを確かめる。**
 * 基板の R7（510Ω・VIN→KLINE）が K を 12V に吊っているので、カプラを車両へ
 * 挿していなければ（＝K 線が開放端なら）TX→K→RX が閉じる。ハーネスを作った
 * 直後にこれを回せば、入れ違いも短絡も車両の前へ行く前に潰せる。 */
static void cmdLoop() {
  out("-- K ライン折り返し（車両に挿していないこと）--\n");
  klRaw();
  digitalWrite(PIN_KL_TX, HIGH); delay(5); int hi = digitalRead(PIN_KL_RX);
  digitalWrite(PIN_KL_TX, LOW);  delay(5); int lo = digitalRead(PIN_KL_RX);
  digitalWrite(PIN_KL_TX, HIGH); klUart();
  outf("  DC  TX=H→RX=%d / TX=L→RX=%d  %s\n", hi, lo,
       (hi == 1 && lo == 0) ? "経路成立"
     : (hi == lo) ? "**RX が動かない。K が GND か 12V に落ちている疑い**"
     : "**論理が反転。VBAT と KLINE の入れ違いを疑う**");
  uint8_t tx[64], r[8];
  uint32_t seed = 0x12345678;
  int bad = 0, tot = 0;
  for (int k = 0; k < 16; k++) {
    for (int i = 0; i < 64; i++) { seed = seed * 1664525u + 1013904223u; tx[i] = seed >> 24; }
    xfer(tx, 64, r, sizeof r, 40, false);
    bad += echoBad + (64 - echoGot); tot += 64;
  }
  outf("  %lu bps で %d バイト 誤り %d %s\n", (unsigned long)klBaud, tot, bad,
       bad ? "← **異常**" : "← 健全");
}

static void cmdObd() {
  static const uint8_t IN[5] = {0xC1, 0x33, 0xF1, 0x81, 0x66};
  uint8_t r[64];
  keepOn = false;
  out("-- 標準 OBD 層（ISO 14230-4 KWP FAST）--\n");
  klBreak(25, 25);
  int n = xfer(IN, 5, r, sizeof r, 400, false);
  if (n <= 0) { out("  StartCommunication に無応答\n"); return; }
  dump("  init 応答 ", r, n);
  for (uint8_t pid : {0x0C, 0x0D}) {
    uint8_t q[6] = {0xC2, 0x33, 0xF1, 0x01, pid, 0};
    q[5] = csumAdd(q, 5);
    n = xfer(q, 6, r, sizeof r, 300, false);
    if (n <= 0) { outf("  %02X 無応答\n", pid); continue; }
    dump("  ", r, n);
    if (n >= 7 && r[3] == 0x41 && r[4] == 0x0C) outf("  → 回転数 %d rpm\n", ((r[5] << 8) | r[6]) / 4);
    if (n >= 6 && r[3] == 0x41 && r[4] == 0x0D) outf("  → 車速 %d km/h\n", r[5]);
    delay(60);
  }
}

/* ── OTA ─────────────────────────────────────────────────
 * **J3 のジャンパ操作を無くすため。** 探索フェーズは「仮説が外れたら試す」の
 * 繰り返しで、土台に任意バイト列を置いてもコード側の修正は出る（実際に k の
 * 抜けが出た）。焼き直しの回数が読めないので OTA を入れる。
 *
 * **SSID とパスワードはソースに書かない。** このリポジトリは PUBLIC。
 * BLE で設定して NVS に置く（`HANDOFF.md` の「設定は BLE 経由」と同じ枠）。
 * NVS は暗号化されていないので、機密扱いの資格情報は入れないこと。
 *
 * **OTA は既定で切。** `ota on` で明示的に有効化し、再起動で戻る。LAN に
 * 無認証の書き込み口を開き続けない。
 *
 * **J3 は最後の逃げ道として残す。** 壊れたファームを飛ばすと BLE も OTA も
 * 死ぬので、有線の経路を潰してはいけない。 */
static Preferences prefs;
static bool otaOn = false;
static WiFiMulti wifiMulti;

/* **複数の AP を登録できる。** 家では自宅の WiFi、バイクの横ではスマホの
 * テザリングになるため。`WiFiMulti` が**見えているものを自動で選ぶ**ので、
 * 場所によって設定を変える必要は無い。 */
static const int WIFI_MAX = 4;

static void cmdWifi(const char *arg) {
  prefs.begin("mc52", false);
  int n = prefs.getInt("wn", 0);
  if (!*arg) {
    if (!n) out("保存済みの WiFi: (なし)\n");
    for (int i = 0; i < n; i++) {
      char k[8]; snprintf(k, sizeof k, "s%d", i);
      outf("  [%d] %s\n", i, prefs.getString(k, "").c_str());
    }
    prefs.end(); return;
  }
  if (!strcmp(arg, "clear")) { prefs.putInt("wn", 0); prefs.end(); out("全部消した\n"); return; }
  char buf[160]; strncpy(buf, arg, sizeof buf - 1); buf[sizeof buf - 1] = 0;
  char *sp = strchr(buf, ' ');
  if (!sp) { prefs.end(); out("wifi <ssid> <pass>  /  wifi clear  /  wifi（一覧）\n"); return; }
  *sp++ = 0;
  int slot = -1;
  for (int i = 0; i < n; i++) {
    char k[8]; snprintf(k, sizeof k, "s%d", i);
    if (prefs.getString(k, "") == buf) { slot = i; break; }
  }
  if (slot < 0) {
    if (n >= WIFI_MAX) { prefs.end(); outf("上限 %d 個。wifi clear で消す\n", WIFI_MAX); return; }
    slot = n++;
  }
  char ks[8], kp[8];
  snprintf(ks, sizeof ks, "s%d", slot); snprintf(kp, sizeof kp, "p%d", slot);
  prefs.putString(ks, buf); prefs.putString(kp, sp); prefs.putInt("wn", n);
  prefs.end();
  outf("[%d] に保存した SSID=%s（パスワードは表示しない）。登録 %d 個\n", slot, buf, n);
}

static void cmdOta(const char *arg) {
  if (*arg == '0' || !strncmp(arg, "off", 3)) {
    if (otaOn) ArduinoOTA.end();
    WiFi.disconnect(true); WiFi.mode(WIFI_OFF);
    otaOn = false; out("OTA 切\n"); return;
  }
  if (otaOn) { outf("既に有効  IP %s\n", WiFi.localIP().toString().c_str()); return; }
  prefs.begin("mc52", true);
  int n = prefs.getInt("wn", 0);
  if (!n) { prefs.end(); out("先に wifi <ssid> <pass> で設定する\n"); return; }
  WiFi.mode(WIFI_STA);
  for (int i = 0; i < n; i++) {
    char ks[8], kp[8];
    snprintf(ks, sizeof ks, "s%d", i); snprintf(kp, sizeof kp, "p%d", i);
    String ss = prefs.getString(ks, ""), pw = prefs.getString(kp, "");
    if (ss.length()) wifiMulti.addAP(ss.c_str(), pw.c_str());
  }
  prefs.end();
  outf("登録 %d 個から、見えているものを探す…（テザリングなら先に ON に）\n", n);
  uint32_t t0 = millis();
  while (wifiMulti.run() != WL_CONNECTED && millis() - t0 < 25000) delay(200);
  if (WiFi.status() != WL_CONNECTED) { out("どれにも繋がらない\n"); WiFi.mode(WIFI_OFF); return; }
  outf("接続: %s\n", WiFi.SSID().c_str());
  ArduinoOTA.setHostname("mc52-explore");
  ArduinoOTA.onStart([] { out("OTA 開始\n"); });
  ArduinoOTA.onEnd([]   { out("OTA 完了。再起動する\n"); });
  ArduinoOTA.onProgress([](unsigned p, unsigned t) {
    static int last = -1; int pc = t ? p * 100 / t : 0;
    if (pc / 20 != last) { last = pc / 20; outf("  %d%%\n", pc); }
  });
  ArduinoOTA.onError([](ota_error_t e) { outf("OTA 失敗 %d\n", (int)e); });
  ArduinoOTA.begin();
  otaOn = true;
  String ip = WiFi.localIP().toString();
  outf("**OTA 有効  IP %s  RSSI %d dBm**\n", ip.c_str(), WiFi.RSSI());
  outf("  pio run -e explore_ota -t upload --upload-port %s\n", ip.c_str());
}

/* ── 記録 ─────────────────────────────────────────────────
 * **生フレームをそのまま追記する。** 復号は Mac 側でやる。
 * テーブルのバイト配置も噴射時間の単位も未確定なので、解釈して書くと
 * 間違いが確定した時点で過去のログが全部無価値になる。`gear.md` の
 * 「ログには ECU の生値を記録する」を一段下（フィールド解釈そのもの）へ
 * 適用しただけ。
 *
 *   ファイル先頭   "MC52" ver:u8  開始壁時計:u32(unix)
 *   レコード       type:u8  dt:u16(前レコードからの ms)  len:u8  data[len]
 *
 * **要求も記録する。** 何を訊いて何が返ったかが対になるので診断に効く。
 *
 * 書き出しは 4KB たまるか 5 秒で追記する。IG 連動で電源が落ちる基板なので、
 * 停止を押すまで 1 バイトも書かない作りだと切った瞬間に全部消える。 */
static const uint8_t LOG_VER = 1;

static File logFile;
static bool recOn = false;
static uint8_t logBuf[4096];
static size_t logLen = 0;
static uint32_t lastRecMs = 0, lastFlush = 0, logBytes = 0, logRecs = 0;

static void logFlush() {
  if (!logFile || !logLen) return;
  logFile.write(logBuf, logLen);
  logFile.flush();
  logBytes += logLen;
  logLen = 0;
  lastFlush = millis();
}
static void logRec(uint8_t type, const uint8_t *d, size_t n) {
  if (!recOn || !logFile || n > 255) return;
  uint32_t now = millis();
  uint32_t dt = lastRecMs ? now - lastRecMs : 0;
  lastRecMs = now;
  if (logLen + 4 + n > sizeof logBuf) logFlush();
  logBuf[logLen++] = type;
  logBuf[logLen++] = dt > 0xFFFF ? 0xFF : dt & 0xFF;
  logBuf[logLen++] = dt > 0xFFFF ? 0xFF : (dt >> 8) & 0xFF;
  logBuf[logLen++] = (uint8_t)n;
  memcpy(logBuf + logLen, d, n); logLen += n;
  logRecs++;
}
static void logTick() { if (recOn && millis() - lastFlush > 5000) logFlush(); }

static void cmdRec(const char *argIn) {
  /* `rec on <名前>` の `on` を名前として食っていた（実機で `on bench.bin` が
   * 出来た）。先頭の語を見てから残りを名前にする。名前に空白は許さない —— 
   * 転送の BEGIN 行が空白区切りなので、名前に入ると解析が壊れる。 */
  char tmp[64]; strncpy(tmp, argIn, sizeof tmp - 1); tmp[sizeof tmp - 1] = 0;
  char *arg = tmp;
  if (!strncmp(arg, "on", 2) && (arg[2] == 0 || arg[2] == ' ')) {
    arg += 2; while (*arg == ' ') arg++;
  }
  for (char *p = arg; *p; p++) if (*p == ' ') *p = '_';
  if (!strncmp(arg, "off", 3) || *arg == '0') {
    if (!recOn) { out("記録していない\n"); return; }
    logFlush(); logFile.close(); recOn = false;
    outf("停止。%lu レコード / %lu バイト\n", (unsigned long)logRecs, (unsigned long)logBytes);
    return;
  }
  if (recOn) { outf("記録中（%lu レコード）\n", (unsigned long)logRecs); return; }
  char name[48];
  time_t t = time(nullptr);
  if (*arg) snprintf(name, sizeof name, "/%s.bin", arg);
  else {
    struct tm tmv; localtime_r(&t, &tmv);
    snprintf(name, sizeof name, "/%04d%02d%02d_%02d%02d%02d.bin",
             tmv.tm_year + 1900, tmv.tm_mon + 1, tmv.tm_mday, tmv.tm_hour, tmv.tm_min, tmv.tm_sec);
  }
  logFile = LittleFS.open(name, "w");
  if (!logFile) { outf("作れない: %s\n", name); return; }
  uint8_t hdr[9] = {'M','C','5','2', LOG_VER,
                    (uint8_t)(t & 0xFF), (uint8_t)((t >> 8) & 0xFF),
                    (uint8_t)((t >> 16) & 0xFF), (uint8_t)((t >> 24) & 0xFF)};
  logFile.write(hdr, sizeof hdr);
  logLen = 0; logBytes = sizeof hdr; logRecs = 0; lastRecMs = 0; lastFlush = millis();
  recOn = true;
  outf("記録開始 %s（壁時計 %lu）%s\n", name, (unsigned long)t,
       t < 1700000000 ? "  ★ 時刻が未設定。time <unix> で合わせる" : "");
}

static void cmdLs() {
  File root = LittleFS.open("/");
  if (!root) { out("開けない\n"); return; }
  int n = 0; size_t tot = 0;
  for (File f = root.openNextFile(); f; f = root.openNextFile()) {
    outf("  %-28s %8u バイト\n", f.name(), (unsigned)f.size());
    tot += f.size(); n++;
  }
  outf("%d ファイル / %u バイト  空き %u KB\n", n, (unsigned)tot,
       (unsigned)((LittleFS.totalBytes() - LittleFS.usedBytes()) / 1024));
}

/* base64 で notify のテキスト経路に流す。実測 33KB/s に対し実効 25KB/s。
 * **CRC32 を添えて Mac 側で検証する。** */
static const char B64[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
static uint32_t crc32(uint32_t c, const uint8_t *b, size_t n) {
  c = ~c;
  for (size_t i = 0; i < n; i++) {
    c ^= b[i];
    for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xEDB88320u & (-(int32_t)(c & 1)));
  }
  return ~c;
}
static void cmdGet(const char *name) {
  char path[64]; snprintf(path, sizeof path, "%s%s", *name == '/' ? "" : "/", name);
  File f = LittleFS.open(path, "r");
  if (!f) { outf("無い: %s\n", path); return; }
  size_t sz = f.size();
  outf("BEGIN %s %u\n", path, (unsigned)sz);
  uint8_t in[45]; char line[64];
  uint32_t crc = 0;
  while (true) {
    int n = f.read(in, sizeof in);
    if (n <= 0) break;
    crc = crc32(crc, in, n);
    int p = 0;
    for (int i = 0; i < n; i += 3) {
      uint32_t v = in[i] << 16 | (i + 1 < n ? in[i+1] << 8 : 0) | (i + 2 < n ? in[i+2] : 0);
      line[p++] = B64[(v >> 18) & 63];
      line[p++] = B64[(v >> 12) & 63];
      line[p++] = i + 1 < n ? B64[(v >> 6) & 63] : '=';
      line[p++] = i + 2 < n ? B64[v & 63] : '=';
    }
    line[p++] = '\n'; line[p] = 0;
    out(line);
  }
  f.close();
  outf("END %08lX\n", (unsigned long)crc);
}

// ── コマンド解釈 ─────────────────────────────────────────
static int hexBytes(const char *s, uint8_t *b, size_t cap) {
  int n = 0, hi = -1;
  for (; *s && n < (int)cap; s++) {
    int d = (*s >= '0' && *s <= '9') ? *s - '0'
          : (*s >= 'a' && *s <= 'f') ? *s - 'a' + 10
          : (*s >= 'A' && *s <= 'F') ? *s - 'A' + 10 : -1;
    if (d < 0) { if (hi >= 0) { b[n++] = hi; hi = -1; } continue; }
    if (hi < 0) hi = d; else { b[n++] = hi * 16 + d; hi = -1; }
  }
  if (hi >= 0 && n < (int)cap) b[n++] = hi;
  return n;
}

static void help() {
  outf("\n== MC52 K ライン探索コンソール ==  ビルド %s %s\n", __DATE__, __TIME__);
  out(
      "[土台] これがあれば未知のプロトコルを焼き直さずに試せる\n"
      "  x <hex..>   バイト列をそのまま送って返りを見る\n"
      "  X <hex..>   チェックサム（総和の2の補数）を付けて送る\n"
      "  brk <ms>    K 線を指定 ms だけ Low に落とす（ELM327 にできない部分）\n"
      "  baud <n>    K ラインの速度を変える（既定 10400）\n"
      "[独自層] 本命。ELM327 では原理的に叩けない層\n"
      "  w           初期化（70ms ブレーク → ウェイクアップ 2 種）\n"
      "  s           テーブル 0x00〜0xFF 総当たり ★ 最初にやること\n"
      "  d           0xD1（index4 = 噛み合い状態）\n"
      "  m           0x11 → 0x10（センサ群。index18-19 が噴射時間か）\n"
      "  t <XX>      任意のテーブルを 1 回読む\n"
      "  ka <0|1>    keep-alive の入切（既定は w で入る）\n"
      "[実時間] 生バイトを機械可読な行で押し出す。解釈は Mac 側（klwatch.py）\n"
      "  poll <TT..> [ms]    そのテーブルを周期読みして P 行で流す（既定 200ms）\n"
      "                      BLE が切れても止まらない。rec と併用すると記録も残る\n"
      "  poll off            停止   poll だけで現在の状態\n"
      "[標準層] 足場。ELM327 で既に取れているもの\n"
      "  o           fast init して 0C / 0D を読む\n"
      "[物理層]\n"
      "  k           K ライン折り返し（車両に挿していない状態で。配線の検証）\n"
      "[記録] 生フレームを LittleFS へ追記。復号は Mac 側\n"
      "  rec on [名前]       記録開始（名前を省くと日時）   rec off  停止\n"
      "  ls / df / rm <名前> 一覧 / 空き / 削除\n"
      "  get <名前>          BLE で吸い出す（base64 ＋ CRC32）\n"
      "  note <文字列>       ログに目印を入れる\n"
      "[更新] J3 のジャンパ操作を無くす\n"
      "  wifi                登録済みの一覧   wifi clear  全消し\n"
      "  wifi <ssid> <pass>  NVS に保存（最大 4 件。ソースには書かない）\n"
      "                      家の WiFi とスマホのテザリングを両方入れておける\n"
      "  ota on | off        OTA を有効化して IP を返す（既定は切。再起動で戻る）\n"
      "[その他]\n"
      "  time <unix> 壁時計を合わせる（GPS ログとの突き合わせに要る）\n"
      "  ?           この一覧\n"
      "出所と信頼度は PROVENANCE.md。**MC52 では全部未検証。**\n");
}

static void runCmd(char *line) {
  while (*line == ' ') line++;
  char *arg = strchr(line, ' ');
  if (arg) { *arg++ = 0; while (*arg == ' ') arg++; } else arg = (char *)"";

  if (!strcmp(line, "?") || !strcmp(line, "h")) { help(); return; }
  if (!strcmp(line, "w")) { cmdPropInit(); return; }
  if (!strcmp(line, "s")) { cmdScan(); return; }
  if (!strcmp(line, "d")) { cmdTable(0xD1); return; }
  if (!strcmp(line, "m")) { cmdTable(0x11); cmdTable(0x10); return; }
  if (!strcmp(line, "poll")) { cmdPoll(arg); return; }
  if (!strcmp(line, "o")) { cmdObd(); return; }
  if (!strcmp(line, "k")) { cmdLoop(); return; }
  if (!strcmp(line, "rec")) { cmdRec(arg); return; }
  if (!strcmp(line, "ls"))  { cmdLs(); return; }
  if (!strcmp(line, "get")) { if (*arg) cmdGet(arg); else out("get <名前>\n"); return; }
  if (!strcmp(line, "rm")) {
    char path[64]; snprintf(path, sizeof path, "%s%s", *arg == '/' ? "" : "/", arg);
    outf(LittleFS.remove(path) ? "消した %s\n" : "消せない %s\n", path); return;
  }
  if (!strcmp(line, "df")) {
    outf("容量 %u KB / 使用 %u KB / 空き %u KB\n",
         (unsigned)(LittleFS.totalBytes()/1024), (unsigned)(LittleFS.usedBytes()/1024),
         (unsigned)((LittleFS.totalBytes()-LittleFS.usedBytes())/1024)); return;
  }
  if (!strcmp(line, "note")) { logRec(T_NOTE, (const uint8_t*)arg, strlen(arg)); out("記録した\n"); return; }
  if (!strcmp(line, "wifi")) { cmdWifi(arg); return; }
  if (!strcmp(line, "ota")) { cmdOta(arg); return; }
  if (!strcmp(line, "t")) { uint8_t t[1]; if (hexBytes(arg, t, 1) == 1) cmdTable(t[0]); else out("t の後に 16 進 2 桁\n"); return; }
  if (!strcmp(line, "ka")) { keepOn = (*arg == '1'); outf("keep-alive %s\n", keepOn ? "入" : "切"); return; }
  if (!strcmp(line, "baud")) { klBaud = atoi(arg); klUart(); outf("K ライン %lu bps\n", (unsigned long)klBaud); return; }
  if (!strcmp(line, "brk")) {
    uint32_t ms = atoi(arg); if (!ms) ms = 70;
    klBreak(ms, 120); outf("%lu ms の Low を出した\n", (unsigned long)ms); return;
  }
  if (!strcmp(line, "time")) {
    time_t t = (time_t)atoll(arg);
    struct timeval tv = {t, 0}; settimeofday(&tv, nullptr);
    outf("壁時計を %s に合わせた", ctime(&t)); return;
  }
  if (!strcmp(line, "x") || !strcmp(line, "X")) {
    uint8_t b[64];
    int n = hexBytes(arg, b, sizeof b - 1);
    if (n < 1) { out("バイト列が無い\n"); return; }
    if (line[0] == 'X') { b[n] = csum2c(b, n); n++; }
    dump("送信 ", b, n);
    uint8_t r[192];
    int m = xfer(b, n, r, sizeof r, 400, false);
    outf("エコー %d/%d バイト 誤り %d %s\n", echoGot, n, echoBad,
         (echoGot == n && !echoBad) ? "← 物理層は健全" : "← **K ラインに異常**");
    if (m <= 0) { out("応答なし\n"); return; }
    dump("応答 ", r, m);
    outf("  総和 0x%02X %s\n", (uint8_t)[&]{ uint8_t s=0; for (int i=0;i<m;i++) s+=r[i]; return s; }(),
         csOk2c(r, m) ? "（2の補数チェックサムとして整合）" : "");
    return;
  }
  outf("不明なコマンド: %s（? で一覧）\n", line);
}

// ── 入力（BLE とシリアルで同じパーサを共有） ──────────────
static char cmdBuf[128];
static size_t cmdLen = 0;
static volatile bool pending = false;
static char pendingCmd[128];

class RxCb : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *c) override {
    std::string v = c->getValue();
    for (char ch : v) {
      if (ch == '\n' || ch == '\r') {
        if (cmdLen) { cmdBuf[cmdLen] = 0; strncpy(pendingCmd, cmdBuf, sizeof pendingCmd); pending = true; cmdLen = 0; }
      } else if (cmdLen < sizeof cmdBuf - 1) cmdBuf[cmdLen++] = ch;
    }
    if (cmdLen && v.find('\n') == std::string::npos && v.find('\r') == std::string::npos) {
      // 改行なしで来た場合も 1 コマンドとして受ける（端末によっては付かない）
      cmdBuf[cmdLen] = 0; strncpy(pendingCmd, cmdBuf, sizeof pendingCmd); pending = true; cmdLen = 0;
    }
  }
};
class SrvCb : public BLEServerCallbacks {
  void onConnect(BLEServer *) override { bleConn = true; }
  void onDisconnect(BLEServer *s) override { bleConn = false; s->startAdvertising(); }
};

void setup() {
  Serial.begin(115200);
  delay(400);
  klRaw(); digitalWrite(PIN_KL_TX, HIGH); klUart();
  if (!LittleFS.begin(true)) Serial.println("LittleFS をマウントできない");

  BLEDevice::init("MC52-explore");
  BLEDevice::setMTU(247);
  BLEServer *srv = BLEDevice::createServer();
  srv->setCallbacks(new SrvCb());
  BLEService *svc = srv->createService(SVC_UUID);
  txChar = svc->createCharacteristic(TX_UUID, BLECharacteristic::PROPERTY_NOTIFY);
  txChar->addDescriptor(new BLE2902());
  BLECharacteristic *rx = svc->createCharacteristic(
      RX_UUID, BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  rx->setCallbacks(new RxCb());
  svc->start();
  srv->getAdvertising()->addServiceUUID(SVC_UUID);
  srv->getAdvertising()->start();

  help();
  out("BLE: MC52-explore として広告中\n");
}

void loop() {
  if (otaOn) ArduinoOTA.handle();
  logTick();
  pollTick();
  keepAlive();
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (cmdLen) { cmdBuf[cmdLen] = 0; cmdLen = 0; runCmd(cmdBuf); out("\n"); }
    } else if (cmdLen < sizeof cmdBuf - 1) cmdBuf[cmdLen++] = ch;
  }
  if (pending) { pending = false; runCmd(pendingCmd); out("\n"); }
  delay(2);
}
