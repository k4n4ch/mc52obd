/* MC52 基板 — 机上自己診断（バイク不要）
 *
 * **バイクに繋がずに確かめられるものを全部ここでやる。** 基板上の R7（510Ω・
 * VIN→KLINE）が K ラインのプルアップなので、`J1` の KLINE を未接続にしたまま
 * 12V を入れれば K は 12V に吊られ、**TX→K→RX の折り返しが基板内で閉じる。**
 * L9637D は pin3=3V3（ロジック VCC）/ pin7=VIN（バス側 VS）なので、
 * **「VCC 3〜7V だが試験は 5V のみ」という唯一の未検証点を机上で潰せる。**
 *
 * HANDOFF.md に数字だけ書いて一度も測っていない主張が 3 つある。全部ここで測る。
 *   1. L9637D が VCC=3.3V で K ラインを通すか
 *   2. バイナリ追記 0.32MB/時・16MB で約 40 時間
 *   3. BLE が MTU 247 ＋ 2M PHY で 20〜50KB/s（既定のままだと 1〜2KB/s で実用外）
 *
 * 使い方: J3 に USB-UART を当て 115200bps。単文字コマンドを送る。
 */
#include <Arduino.h>
#include <LittleFS.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

static const int PIN_KL_TX = 17;
static const int PIN_KL_RX = 18;
HardwareSerial KL(1);

// ── 1. 基板の素性 ────────────────────────────────────────
static void cmdInfo() {
  Serial.println("-- 基板 --");
  Serial.printf("  チップ      %s rev%d  %dコア\n",
                ESP.getChipModel(), ESP.getChipRevision(), ESP.getChipCores());
  Serial.printf("  フラッシュ  %u MB（期待値 16）\n", ESP.getFlashChipSize() / (1024 * 1024));
  size_t ps = ESP.getPsramSize();
  Serial.printf("  PSRAM       %u MB（期待値 8）%s\n", ps / (1024 * 1024),
                ps == 0 ? "  ★ 検出されない" : "");
  Serial.printf("  空きヒープ  %u バイト\n", ESP.getFreeHeap());
  Serial.printf("  リセット要因 %d\n", (int)esp_reset_reason());
}

/* ── 2. K ライン折り返し ──────────────────────────────────
 * **これが 3.3V 動作の合否そのもの。**
 * まず DC で両方向を確かめ、次に 10400bps で誤りを数え、最後に速度を上げて
 * 余裕を見る。速度余裕は「10400 でぎりぎり通っている」のか「十分余裕がある」
 * のかを分ける。前者なら温度や個体差で落ちる。 */
static void klIdle() { KL.end(); pinMode(PIN_KL_TX, OUTPUT); pinMode(PIN_KL_RX, INPUT); }

static void cmdKlineDc() {
  Serial.println("-- K ライン DC --");
  klIdle();
  digitalWrite(PIN_KL_TX, HIGH); delay(5);
  int hi = digitalRead(PIN_KL_RX);
  digitalWrite(PIN_KL_TX, LOW);  delay(5);
  int lo = digitalRead(PIN_KL_RX);
  digitalWrite(PIN_KL_TX, HIGH);
  Serial.printf("  TX=H → RX=%d（期待 1。R7 で K が 12V に吊られている）\n", hi);
  Serial.printf("  TX=L → RX=%d（期待 0。L9637D が K を引き下げている）\n", lo);
  if (hi == 1 && lo == 0) Serial.println("  **DC 経路は 3.3V で成立**");
  else if (hi == lo)      Serial.println("  ★ RX が動かない。VS(12V) が来ていないか U3 が死んでいる");
  else                    Serial.println("  ★ 論理が反転している。配線を疑う");
}

/* 指定 bps で疑似乱数列を送り、返ってくるエコーと突き合わせて誤りを数える。 */
static void klEcho(uint32_t baud, size_t nbytes) {
  KL.end();
  KL.begin(baud, SERIAL_8N1, PIN_KL_RX, PIN_KL_TX);
  delay(20);
  while (KL.available()) KL.read();

  uint32_t seed = 0x12345678, chk = 0x12345678;
  size_t sent = 0, got = 0, bad = 0;
  const size_t CH = 32;                       // FIFO を溢れさせない塊で往復させる
  uint32_t t0 = micros();
  while (sent < nbytes) {
    uint8_t tx[CH];
    size_t n = min(CH, nbytes - sent);
    for (size_t i = 0; i < n; i++) { seed = seed * 1664525u + 1013904223u; tx[i] = seed >> 24; }
    KL.write(tx, n);
    KL.flush();
    uint32_t w = millis();
    size_t r = 0;
    while (r < n && millis() - w < 200) {
      if (!KL.available()) continue;
      uint8_t c = KL.read();
      chk = chk * 1664525u + 1013904223u;
      if (c != (uint8_t)(chk >> 24)) bad++;
      r++; got++;
    }
    if (r < n) { for (size_t i = r; i < n; i++) chk = chk * 1664525u + 1013904223u; }
    sent += n;
  }
  uint32_t us = micros() - t0;
  Serial.printf("  %6lu bps  送信 %u  受信 %u  誤り %u  (%.1f ms)%s\n",
                (unsigned long)baud, (unsigned)sent, (unsigned)got, (unsigned)bad,
                us / 1000.0, (got == sent && bad == 0) ? "  OK" : "  ★");
}

static void cmdKline() {
  cmdKlineDc();
  Serial.println("-- K ライン エコー --");
  klEcho(10400, 1024);                        // 本番の速度
  Serial.println("  以下は余裕の確認（通らなくても本番には影響しない）");
  for (uint32_t b : {19200u, 38400u, 57600u, 115200u}) klEcho(b, 512);
  klIdle();
}

/* ── 3. LittleFS ─────────────────────────────────────────
 * 設計は「4KB たまるか 5 秒経過で周期追記」。同じ 4KB 単位で測る。 */
static void cmdFs() {
  Serial.println("-- LittleFS --");
  if (!LittleFS.begin(true)) { Serial.println("  ★ マウントできない"); return; }
  Serial.printf("  容量 %u KB / 使用 %u KB\n",
                (unsigned)(LittleFS.totalBytes() / 1024), (unsigned)(LittleFS.usedBytes() / 1024));

  static uint8_t buf[4096];
  for (size_t i = 0; i < sizeof buf; i++) buf[i] = (uint8_t)i;
  const size_t CHUNKS = 64;                   // 256KB

  LittleFS.remove("/bench.bin");
  File f = LittleFS.open("/bench.bin", "w");
  if (!f) { Serial.println("  ★ 作成できない"); return; }
  uint32_t t0 = millis();
  for (size_t i = 0; i < CHUNKS; i++) { f.write(buf, sizeof buf); f.flush(); }
  f.close();
  uint32_t wms = millis() - t0;

  f = LittleFS.open("/bench.bin", "r");
  size_t bad = 0, rd = 0;
  t0 = millis();
  while (f.available()) {
    size_t n = f.read(buf, sizeof buf);
    for (size_t i = 0; i < n; i++) if (buf[i] != (uint8_t)i) bad++;
    rd += n;
  }
  f.close();
  uint32_t rms = millis() - t0;
  LittleFS.remove("/bench.bin");

  float kb = CHUNKS * 4.0f;
  Serial.printf("  書き込み %.0f KB / %lu ms = %.0f KB/s（4KB ごとに flush）\n", kb, (unsigned long)wms, kb * 1000 / wms);
  Serial.printf("  読み出し %u KB / %lu ms = %.0f KB/s  不一致 %u\n",
                (unsigned)(rd / 1024), (unsigned long)rms, (rd / 1024.0f) * 1000 / rms, (unsigned)bad);
  // 設計の主張: バイナリ 0.32MB/時
  float freeMB = (LittleFS.totalBytes() - LittleFS.usedBytes()) / 1048576.0f;
  Serial.printf("  空き %.1f MB → 0.32MB/時 なら **%.0f 時間**（主張は約 40 時間）\n", freeMB, freeMB / 0.32f);
}

/* ── 4. BLE ──────────────────────────────────────────────
 * 既定（MTU 23・1M PHY）だと 1〜2KB/s で 1 時間ぶんの転送に 12〜25 分かかり
 * 実用外、というのが設計時の見積もり。**実測して確かめる。**
 * Mac 側は tools/ の bleak スクリプトで受ける（未作成）。 */
static const char *SVC_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";
static const char *TX_UUID  = "6e400003-b5a3-f393-e0a9-e50e24dcca9e";
static BLECharacteristic *txChar = nullptr;
static volatile bool bleConnected = false;
static volatile uint16_t bleMtu = 23;

class SrvCb : public BLEServerCallbacks {
  void onConnect(BLEServer *, esp_ble_gatts_cb_param_t *p) override {
    bleConnected = true;
    esp_ble_gap_set_prefered_phy(p->connect.remote_bda, 0, ESP_BLE_GAP_PHY_2M_PREF_MASK,
                                 ESP_BLE_GAP_PHY_2M_PREF_MASK, 0);
  }
  void onDisconnect(BLEServer *s) override { bleConnected = false; s->startAdvertising(); }
  void onMtuChanged(BLEServer *, esp_ble_gatts_cb_param_t *p) override { bleMtu = p->mtu.mtu; }
};

static void cmdBle() {
  Serial.println("-- BLE --");
  static bool inited = false;
  if (!inited) {
    BLEDevice::init("MC52-selftest");
    BLEDevice::setMTU(247);
    BLEServer *srv = BLEDevice::createServer();
    srv->setCallbacks(new SrvCb());
    BLEService *svc = srv->createService(SVC_UUID);
    txChar = svc->createCharacteristic(TX_UUID, BLECharacteristic::PROPERTY_NOTIFY);
    txChar->addDescriptor(new BLE2902());
    svc->start();
    srv->getAdvertising()->addServiceUUID(SVC_UUID);
    srv->getAdvertising()->start();
    inited = true;
  }
  Serial.println("  MC52-selftest として広告中。Mac から接続してください（30 秒待つ）");
  uint32_t t0 = millis();
  while (!bleConnected && millis() - t0 < 30000) delay(50);
  if (!bleConnected) { Serial.println("  接続なし"); return; }
  delay(1500);                                        // MTU / PHY の交渉を待つ
  Serial.printf("  接続。交渉後の MTU = %u（要求 247）\n", bleMtu);

  size_t pay = bleMtu > 3 ? bleMtu - 3 : 20;
  static uint8_t buf[244];
  for (size_t i = 0; i < sizeof buf; i++) buf[i] = (uint8_t)i;
  uint32_t sent = 0;
  t0 = millis();
  while (millis() - t0 < 10000 && bleConnected) {
    txChar->setValue(buf, min(pay, sizeof buf));
    txChar->notify();
    sent += pay;
    delay(1);
  }
  uint32_t ms = millis() - t0;
  Serial.printf("  %u バイト / %lu ms = **%.1f KB/s**\n", (unsigned)sent, (unsigned long)ms, sent / 1024.0f * 1000 / ms);
  Serial.println("  設計の見積もり: 既定 1〜2KB/s（実用外） / MTU拡張＋2M PHY で 20〜50KB/s");
  Serial.printf("  1 時間ぶん（バイナリ 0.32MB）の転送に %.0f 秒\n", 327680.0f / (sent / (ms / 1000.0f)));
}

static void help() {
  Serial.println();
  Serial.println("== MC52 机上自己診断 ==");
  Serial.println("  i  基板の素性（フラッシュ / PSRAM / リセット要因）");
  Serial.println("  k  K ライン折り返し  ★ 3.3V で L9637D が通るかの判定");
  Serial.println("  f  LittleFS の書き込み速度と記録可能時間");
  Serial.println("  b  BLE のスループット（Mac から接続する）");
  Serial.println("  a  i / k / f を続けて実行");
  Serial.println("  h  この一覧");
  Serial.println("バイクへは繋がない。12V を入れ、J1 の KLINE は未接続のままにする。");
}

void setup() {
  Serial.begin(115200);
  delay(400);
  klIdle();
  help();
}

void loop() {
  if (!Serial.available()) return;
  int c = Serial.read();
  switch (c) {
    case 'i': cmdInfo();   break;
    case 'k': cmdKline();  break;
    case 'f': cmdFs();     break;
    case 'b': cmdBle();    break;
    case 'a': cmdInfo(); cmdKline(); cmdFs(); break;
    case 'h': help();      break;
    default:  return;
  }
  Serial.println();
}
