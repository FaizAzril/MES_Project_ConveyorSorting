/*
========================================================================
 PROJECT  : MES CONVEYOR SORTING SYSTEM
 BOARD    : ESP32 DevKit V1
 ACTUATOR : Servo SG90 (signal GPIO 18, powered from its own 5 V buck)
 DATABASE : Firebase Realtime Database (REST over HTTPS)

 FLOW
   Python CV (main.py) writes   /detections/{eventId}
       { class: PERFECT|DEFECT|INVALID, detectedAtMs, ... }
   ESP32 polls the newest detections, then for each new event:
       PERFECT          -> STRAIGHT (servo stays HOME)  -> BIN1
       DEFECT / INVALID -> DIVERT   (servo pushes)      -> BIN2
   The servo fires at  detectedAtMs + TRAVEL_TIME_MS  (t = L / v, measured
   from the camera ROI to the servo arm), using NTP time on both sides.
   After acting, the ESP32 writes back  sortAction + sortedAtMs  so the
   dashboard can compute cycle time. Heartbeat goes to /conveyor.

 LIBRARIES (Arduino Library Manager)
   - ArduinoJson (v7)      - ESP32Servo
 SETUP
   Copy secrets.example.h to secrets.h and fill it in (never commit it).
========================================================================
*/

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>
#include <sys/time.h>
#include <time.h>

#include "secrets.h"  // WIFI_SSID, WIFI_PASSWORD, FIREBASE_HOST, FIREBASE_AUTH

// ── Servo ──────────────────────────────────────────────────────────────
const int SERVO_PIN = 18;
const int HOME_ANGLE = 90;      // arm parallel to the belt (does not block)
const int DIVERT_ANGLE = 180;   // arm pushes the cube to BIN2 (calibrate physically, test U4)
// Conservative SG90 pulse range from the bench tests. Do not widen blindly.
const int SERVO_MIN_PULSE_US = 1000;
const int SERVO_MAX_PULSE_US = 2000;
const unsigned long DIVERT_HOLD_MS = 700;   // arm stays out
const unsigned long HOME_SETTLE_MS = 500;   // time for the arm to get back home

// ── Timing: measure on the real conveyor (test U3) ─────────────────────
// TRAVEL_TIME_MS = distance camera-ROI-centre -> servo arm / belt speed.
// Example: L = 20 cm, v = 8 cm/s  ->  2500 ms.
const uint64_t TRAVEL_TIME_MS = 2500;
const uint64_t SERVO_LEAD_MS = 150;     // start moving slightly early
const uint64_t LATE_LIMIT_MS = 1500;    // later than this -> cube already passed

// ── Network ────────────────────────────────────────────────────────────
const unsigned long POLL_INTERVAL_MS = 400;
const unsigned long HEARTBEAT_INTERVAL_MS = 5000;
const unsigned long HTTP_TIMEOUT_MS = 2500;
const unsigned long WIFI_RETRY_MS = 10000;
const int FETCH_LAST = 5;  // newest detections read per poll

// ── State ──────────────────────────────────────────────────────────────
struct SortJob {
  String eventId;
  bool divert;
  uint64_t dueMs;
};
struct Report {
  String eventId;
  String action;   // STRAIGHT | DIVERT | MISSED
  uint64_t sortedAtMs;
};

const int QUEUE_SIZE = 8;
SortJob jobs[QUEUE_SIZE];
int jobHead = 0, jobCount = 0;
Report reports[QUEUE_SIZE];
int reportHead = 0, reportCount = 0;

Servo sortingServo;
WiFiClientSecure secureClient;

String lastEventKey = "";
bool baselineDone = false;

enum ServoState { SERVO_HOME, SERVO_DIVERTING, SERVO_RETURNING };
ServoState servoState = SERVO_HOME;
unsigned long divertStartedAt = 0;
String divertEventId = "";

unsigned long lastPoll = 0, lastHeartbeat = 0, lastWifiAttempt = 0;

// ── Time ───────────────────────────────────────────────────────────────
uint64_t epochMs() {
  struct timeval tv;
  gettimeofday(&tv, nullptr);
  return (uint64_t)tv.tv_sec * 1000ULL + tv.tv_usec / 1000ULL;
}

bool timeSynced() { return time(nullptr) > 1700000000; }

// ── Helpers ────────────────────────────────────────────────────────────
String authParam(bool first) {
  if (strlen(FIREBASE_AUTH) == 0) return "";
  return String(first ? "?" : "&") + "auth=" + FIREBASE_AUTH;
}

const char* servoStateText() {
  if (servoState == SERVO_DIVERTING) return "DIVERT";
  if (servoState == SERVO_RETURNING) return "RETURNING";
  return "HOME";
}

void moveServo(int angle) {
  sortingServo.write(constrain(angle, 0, 180));
}

bool pushReport(const String& id, const char* action, uint64_t at) {
  if (reportCount >= QUEUE_SIZE) return false;
  int idx = (reportHead + reportCount) % QUEUE_SIZE;
  reports[idx] = {id, String(action), at};
  reportCount++;
  return true;
}

// ── Wi-Fi ──────────────────────────────────────────────────────────────
void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("[WIFI] Connecting");
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    delay(300);
    Serial.print(".");
  }
  Serial.println();
  Serial.println(WiFi.status() == WL_CONNECTED ? "[WIFI] Connected" : "[WIFI] Failed, will retry");
  lastWifiAttempt = millis();
}

void maintainWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  if (millis() - lastWifiAttempt < WIFI_RETRY_MS) return;
  lastWifiAttempt = millis();
  Serial.println("[WIFI] Reconnecting...");
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

// ── Firebase REST ──────────────────────────────────────────────────────
int firebaseRequest(const char* method, const String& path, const String& body, String* response) {
  HTTPClient http;
  String url = String(FIREBASE_HOST) + path;
  if (!http.begin(secureClient, url)) return -1;
  http.setTimeout(HTTP_TIMEOUT_MS);
  int code;
  if (strcmp(method, "GET") == 0) code = http.GET();
  else code = http.sendRequest(method, body);
  if (response && code == HTTP_CODE_OK) *response = http.getString();
  http.end();
  if (code == 401 || code == 403) Serial.println("[FIREBASE] Unauthorized: check FIREBASE_AUTH and rules");
  return code;
}

void pollDetections() {
  String path = "/detections.json?orderBy=%22%24key%22&limitToLast=" + String(FETCH_LAST) + authParam(false);
  String payload;
  int code = firebaseRequest("GET", path, "", &payload);
  if (code != HTTP_CODE_OK) {
    Serial.printf("[FIREBASE] Poll failed: %d\n", code);
    return;
  }

  JsonDocument doc;
  if (deserializeJson(doc, payload)) {
    Serial.println("[JSON] Parse error");
    return;
  }
  if (!doc.is<JsonObject>()) {  // "null" = no detections yet
    baselineDone = true;
    return;
  }
  JsonObject all = doc.as<JsonObject>();

  // Firebase does not keep key order in JSON: sort the (few) keys ourselves.
  String keys[FETCH_LAST];
  int n = 0;
  for (JsonPair kv : all) {
    if (n >= FETCH_LAST) break;
    keys[n++] = String(kv.key().c_str());
  }
  for (int i = 1; i < n; i++) {
    String k = keys[i];
    int j = i - 1;
    while (j >= 0 && keys[j] > k) { keys[j + 1] = keys[j]; j--; }
    keys[j + 1] = k;
  }

  if (!baselineDone) {
    // First read after boot: old events are history, never actuate them.
    if (n > 0) lastEventKey = keys[n - 1];
    baselineDone = true;
    Serial.printf("[FIREBASE] Baseline: %s\n", lastEventKey.c_str());
    return;
  }

  for (int i = 0; i < n; i++) {
    if (keys[i] <= lastEventKey) continue;
    JsonObject ev = all[keys[i]];
    lastEventKey = keys[i];
    if (!ev["sortAction"].isNull()) continue;  // already handled

    String cls = ev["class"] | "INVALID";
    uint64_t detectedAt = ev["detectedAtMs"] | (uint64_t)0;
    if (detectedAt == 0) detectedAt = epochMs();
    bool divert = (cls != "PERFECT");
    uint64_t due = detectedAt + TRAVEL_TIME_MS;
    due = due > SERVO_LEAD_MS ? due - SERVO_LEAD_MS : due;

    if (jobCount >= QUEUE_SIZE) {
      Serial.println("[QUEUE] Full, event dropped");
      pushReport(keys[i], "MISSED", epochMs());
      continue;
    }
    int idx = (jobHead + jobCount) % QUEUE_SIZE;
    jobs[idx] = {keys[i], divert, due};
    jobCount++;
    long long wait = (long long)(due - epochMs());
    Serial.printf("[EVENT] %s %s -> %s in %lld ms\n", keys[i].c_str(), cls.c_str(),
                  divert ? "DIVERT" : "STRAIGHT", wait);
  }
}

void sendHeartbeat() {
  JsonDocument doc;
  doc["deviceOnline"] = true;
  doc["lastHeartbeatMs"] = epochMs();
  doc["servoState"] = servoStateText();
  doc["queueLength"] = jobCount;
  doc["wifiRssi"] = WiFi.RSSI();
  String body;
  serializeJson(doc, body);
  firebaseRequest("PATCH", "/conveyor.json" + authParam(true), body, nullptr);
}

bool sendOneReport() {
  if (reportCount == 0) return false;
  Report& r = reports[reportHead];
  JsonDocument doc;
  doc["sortAction"] = r.action;
  doc["sortedAtMs"] = r.sortedAtMs;
  String body;
  serializeJson(doc, body);
  int code = firebaseRequest("PATCH", "/detections/" + r.eventId + ".json" + authParam(true), body, nullptr);
  if (code == HTTP_CODE_OK) {
    reportHead = (reportHead + 1) % QUEUE_SIZE;
    reportCount--;
    return true;
  }
  return false;  // keep it, retry later (offline buffer)
}

// ── Sorting state machine (non-blocking) ──────────────────────────────
void updateSorting() {
  uint64_t now = epochMs();

  if (servoState == SERVO_DIVERTING && millis() - divertStartedAt >= DIVERT_HOLD_MS) {
    moveServo(HOME_ANGLE);
    servoState = SERVO_RETURNING;
    divertStartedAt = millis();
  } else if (servoState == SERVO_RETURNING && millis() - divertStartedAt >= HOME_SETTLE_MS) {
    servoState = SERVO_HOME;
    // t_done = cube passed the arm and servo is back home (proposal E.1).
    pushReport(divertEventId, "DIVERT", epochMs());
    Serial.printf("[SERVO] %s done, HOME\n", divertEventId.c_str());
  }

  if (jobCount == 0 || servoState != SERVO_HOME) return;
  SortJob& job = jobs[jobHead];
  if (now < job.dueMs) return;

  if (now - job.dueMs > LATE_LIMIT_MS) {
    Serial.printf("[SORT] %s too late (%llu ms), cube already passed\n",
                  job.eventId.c_str(), (unsigned long long)(now - job.dueMs));
    pushReport(job.eventId, "MISSED", now);
  } else if (job.divert) {
    moveServo(DIVERT_ANGLE);
    servoState = SERVO_DIVERTING;
    divertStartedAt = millis();
    divertEventId = job.eventId;
    Serial.printf("[SERVO] %s DIVERT\n", job.eventId.c_str());
  } else {
    pushReport(job.eventId, "STRAIGHT", now);
    Serial.printf("[SORT] %s STRAIGHT\n", job.eventId.c_str());
  }
  jobHead = (jobHead + 1) % QUEUE_SIZE;
  jobCount--;
}

// Network calls block for up to HTTP_TIMEOUT_MS: only do them when no servo
// action is due soon, so the arm always moves on time.
bool networkWindowFree() {
  if (servoState != SERVO_HOME) return false;
  if (jobCount == 0) return true;
  uint64_t now = epochMs();
  return jobs[jobHead].dueMs > now + HTTP_TIMEOUT_MS + 200;
}

// ── Arduino ────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n=== MES CONVEYOR SORTING · ESP32 + SG90 ===");

  sortingServo.setPeriodHertz(50);
  sortingServo.attach(SERVO_PIN, SERVO_MIN_PULSE_US, SERVO_MAX_PULSE_US);
  moveServo(HOME_ANGLE);

  secureClient.setInsecure();  // prototype: certificate not pinned
  connectWiFi();

  configTime(0, 0, "pool.ntp.org", "time.google.com");
  Serial.print("[NTP] Syncing");
  unsigned long start = millis();
  while (!timeSynced() && millis() - start < 15000) {
    delay(250);
    Serial.print(".");
  }
  Serial.println(timeSynced() ? " OK" : " FAILED (will keep trying)");
}

void loop() {
  maintainWiFi();
  updateSorting();  // always runs, even offline: the conveyor never waits on the internet

  if (WiFi.status() != WL_CONNECTED || !timeSynced() || !networkWindowFree()) return;

  if (millis() - lastPoll >= POLL_INTERVAL_MS) {
    lastPoll = millis();
    pollDetections();
  } else if (reportCount > 0) {
    sendOneReport();
  } else if (millis() - lastHeartbeat >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeat = millis();
    sendHeartbeat();
  }
}
