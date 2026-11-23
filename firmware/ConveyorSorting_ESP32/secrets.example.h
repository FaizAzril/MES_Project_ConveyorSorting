// Copy this file to secrets.h (same folder) and fill in your values.
// secrets.h is ignored by git: never commit real passwords or secrets.
#pragma once

#define WIFI_SSID "PASTE_WIFI_NAME"
#define WIFI_PASSWORD "PASTE_WIFI_PASSWORD"

// Realtime Database URL without trailing slash, e.g.
// "https://your-project-default-rtdb.asia-southeast1.firebasedatabase.app"
#define FIREBASE_HOST "https://PASTE_PROJECT-default-rtdb.asia-southeast1.firebasedatabase.app"

// Firebase Console > Project settings > Service accounts > Database secrets.
// Lets the ESP32 read /detections and write sort results while the rules in
// firebase/database.rules.json keep the database closed to everyone else.
#define FIREBASE_AUTH "PASTE_DATABASE_SECRET"
