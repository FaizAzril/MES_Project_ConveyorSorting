
/*
========================================================
 PROJECT  : CONVEYOR SORTING SYSTEM
 BOARD    : ESP32 DEVKIT V1
 DATABASE : FIREBASE REALTIME DATABASE
 ACTUATOR : SERVO SG90

 FIREBASE PATH:
 /vision.json

 SORTING LOGIC:
 Green     -> Servo mendorong objek
 Non Green -> Servo tetap di HOME

 EVENT IDENTIFICATION:
 vision/lastDetection

========================================================
*/

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>

// ======================================================
// 1. WIFI CONFIGURATION
// ======================================================

// Isi menggunakan Wi-Fi yang akan dipakai ESP32.
// Jangan bagikan password Wi-Fi kepada orang lain.

const char* WIFI_SSID = "";
const char* WIFI_PASSWORD = "";

// ======================================================
// 2. FIREBASE CONFIGURATION
// ======================================================

const char* FIREBASE_URL =
  "";

const char* FIREBASE_PATH =
  "/vision.json";

// ======================================================
// 3. SERVO CONFIGURATION
// ======================================================

Servo sortingServo;

const int SERVO_PIN = 18;

const int HOME_ANGLE = 90;
const int GREEN_ANGLE = 50;

const unsigned long GREEN_HOLD_MS = 700;

// ======================================================
// 4. FIREBASE POLLING CONFIGURATION
// ======================================================

const unsigned long POLLING_INTERVAL = 300;

const unsigned long HTTP_TIMEOUT = 2500;

// ======================================================
// 5. SYSTEM VARIABLES
// ======================================================

WiFiClientSecure secureClient;

bool servoBusy = false;
bool firstRead = true;
bool hasFirebaseBaseline = false;

uint64_t lastProcessedDetection = 0;

unsigned long lastPollingTime = 0;
unsigned long lastDivertTime = 0;
unsigned long lastWifiAttempt = 0;

const unsigned long WIFI_RETRY_INTERVAL = 10000;

// ======================================================
// 6. LABEL NORMALIZATION
// ======================================================

String normalizeLabel(String label) {

  label.trim();
  label.toLowerCase();

  label.replace(" ", "");
  label.replace("_", "");
  label.replace("-", "");

  return label;
}

// ======================================================
// 7. SERVO CONTROL
// ======================================================

void moveServo(int angle) {

  angle = constrain(angle, 0, 180);

  sortingServo.write(angle);

  Serial.print("[SERVO] Position: ");
  Serial.print(angle);
  Serial.println(" degrees");
}

// ======================================================
// 8. GREEN SORTING
// ======================================================

void sortGreen() {

  if (servoBusy) {

    Serial.println("[WARNING] Servo is still active.");

    return;
  }

  Serial.println();
  Serial.println("=================================");
  Serial.println("[SORTING] GREEN OBJECT DETECTED");
  Serial.println("[SERVO] Moving pusher...");
  Serial.println("=================================");

  moveServo(GREEN_ANGLE);

  servoBusy = true;

  lastDivertTime = millis();
}

// ======================================================
// 9. NON-GREEN SORTING
// ======================================================

void sortNonGreen() {

  Serial.println();
  Serial.println("[SORTING] NON-GREEN OBJECT");
  Serial.println("[SERVO] Remains at HOME.");
  Serial.println("[CONVEYOR] Object passes straight.");

  // Tidak menggerakkan servo.
}

// ======================================================
// 10. SERVO AUTOMATIC RETURN
// ======================================================

void updateServo() {

  if (!servoBusy) {
    return;
  }

  if (millis() - lastDivertTime >= GREEN_HOLD_MS) {

    Serial.println("[SORTING] Returning servo to HOME.");

    moveServo(HOME_ANGLE);

    servoBusy = false;

    Serial.println("[SYSTEM] Ready for next object.");
  }
}

// ======================================================
// 11. WIFI CONNECTION
// ======================================================

void connectWiFi() {

  Serial.println();
  Serial.println("[WIFI] Connecting...");

  WiFi.mode(WIFI_STA);

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long startTime = millis();

  while (
    WiFi.status() != WL_CONNECTED &&
    millis() - startTime < 15000
  ) {

    delay(300);

    Serial.print(".");
  }

  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {

    Serial.println("[WIFI] Connected!");

    Serial.print("[WIFI] IP: ");
    Serial.println(WiFi.localIP());

  } else {

    Serial.println("[WIFI] Connection failed.");
  }

  lastWifiAttempt = millis();
}

// ======================================================
// 12. WIFI RECONNECTION
// ======================================================

void maintainWiFi() {

  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  if (
    millis() - lastWifiAttempt >= WIFI_RETRY_INTERVAL
  ) {

    lastWifiAttempt = millis();

    Serial.println("[WIFI] Reconnecting...");

    WiFi.disconnect();

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }
}

// ======================================================
// 13. READ FIREBASE
// ======================================================

void readFirebase() {

  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  HTTPClient http;

  String url =
    String(FIREBASE_URL) +
    String(FIREBASE_PATH);

  Serial.println();
  Serial.println("[FIREBASE] Reading vision data...");

  if (!http.begin(secureClient, url)) {

    Serial.println("[FIREBASE] Connection initialization failed.");

    return;
  }

  http.setTimeout(HTTP_TIMEOUT);

  int responseCode = http.GET();

  if (responseCode == HTTP_CODE_OK) {

    String payload = http.getString();

    JsonDocument doc;

    DeserializationError error =
      deserializeJson(doc, payload);

    if (error) {

      Serial.print("[JSON] Error: ");
      Serial.println(error.c_str());

      http.end();

      return;
    }

    // ---------------------------------------------
    // Extract Firebase fields
    // ---------------------------------------------

    String visionStatus =
      doc["status"] | "";

    String lastClass =
      doc["lastClass"] | "";

    float confidence =
      doc["confidence"] | 0.0f;

    if (doc["lastDetection"].isNull()) {

      Serial.println("[ERROR] lastDetection field missing.");

      http.end();

      return;
    }

    uint64_t detectionId =
      doc["lastDetection"].as<uint64_t>();

    // ---------------------------------------------
    // Display Firebase response
    // ---------------------------------------------

    Serial.println("---------- VISION DATA ----------");

    Serial.print("Status      : ");
    Serial.println(visionStatus);

    Serial.print("Last Class  : ");
    Serial.println(lastClass);

    Serial.print("Confidence  : ");
    Serial.println(confidence);

    Serial.print("Detection ID: ");
    Serial.println((unsigned long long)detectionId);

    Serial.println("---------------------------------");

    // ---------------------------------------------
    // INITIAL SYNCHRONIZATION
    // ---------------------------------------------

    // Pembacaan awal hanya menyimpan event terakhir.
    // Event lama tidak boleh dieksekusi ulang
    // ketika ESP32 baru dinyalakan.

    if (firstRead) {

      lastProcessedDetection = detectionId;

      firstRead = false;
      hasFirebaseBaseline = true;

      Serial.println("[FIREBASE] Initial synchronization complete.");

      http.end();

      return;
    }

    if (!hasFirebaseBaseline) {

      http.end();

      return;
    }

    // ---------------------------------------------
    // CHECK VISION STATUS
    // ---------------------------------------------

    if (visionStatus != "online") {

      // Sinkronkan event lama ketika vision offline
      lastProcessedDetection = detectionId;

      Serial.println("[VISION] System is OFFLINE.");

      http.end();

      return;
    }

    // ---------------------------------------------
    // CHECK NEW DETECTION
    // ---------------------------------------------

    if (detectionId == lastProcessedDetection) {

      Serial.println("[FIREBASE] No new detection.");

      http.end();

      return;
    }

    // Simpan ID terbaru untuk mencegah
    // satu objek diproses berulang kali.

    lastProcessedDetection = detectionId;

    String label = normalizeLabel(lastClass);

    Serial.println("[FIREBASE] New detection event!");

    // ---------------------------------------------
    // SORTING DECISION
    // ---------------------------------------------

    if (label == "green") {

      sortGreen();

    }

    else if (label == "nongreen") {

      sortNonGreen();

    }

    else {

      Serial.println("[WARNING] Unknown object classification.");
    }

  }

  else {

    Serial.print("[FIREBASE] HTTP Error: ");
    Serial.println(responseCode);

    if (responseCode == 401 || responseCode == 403) {

      Serial.println("[FIREBASE] Check database authentication and rules.");
    }
  }

  http.end();
}

// ======================================================
// 14. SETUP
// ======================================================

void setup() {

  Serial.begin(115200);

  delay(500);

  Serial.println();
  Serial.println("====================================");
  Serial.println(" CONVEYOR SORTING SYSTEM");
  Serial.println(" ESP32 + FIREBASE + SG90");
  Serial.println("====================================");

  // Initialize Servo
  sortingServo.setPeriodHertz(50);

  sortingServo.attach(
    SERVO_PIN,
    600,
    2300
  );

  if (!sortingServo.attached()) {

    Serial.println("[ERROR] Servo initialization failed!");

    while (true) {
      delay(1000);
    }
  }

  // Servo starts at HOME
  moveServo(HOME_ANGLE);

  // HTTPS prototype configuration.
  // Certificate verification should be enabled
  // before production use.

  secureClient.setInsecure();

  // Connect Wi-Fi
  connectWiFi();

  Serial.println();
  Serial.println("[SYSTEM] INITIALIZATION COMPLETE");
  Serial.println("[SYSTEM] Waiting for Firebase...");
}

// ======================================================
// 15. MAIN LOOP
// ======================================================

void loop() {

  // Maintain Wi-Fi
  maintainWiFi();

  // Update servo without delay
  updateServo();

  // Poll Firebase only when servo is idle.
  // This initial design assumes objects are
  // sufficiently spaced apart.

  if (
    !servoBusy &&
    WiFi.status() == WL_CONNECTED &&
    millis() - lastPollingTime >= POLLING_INTERVAL
  ) {

    lastPollingTime = millis();

    readFirebase();
  }

}
