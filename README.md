# MES Conveyor Sorting System — Kamera + Firebase + ESP32

Prototipe Mini MES untuk conveyor satu jalur. Webcam memeriksa setiap balok,
hasilnya dicatat ke Firebase Realtime Database, ESP32 menggerakkan servo SG90
untuk menyortir, dan dashboard web menampilkan semuanya, termasuk **video kamera
langsung di dalam dashboard**.

| Objek | Hasil | Aksi ESP32 | Wadah |
|---|---|---|---|
| Merah polos | **PERFECT** | servo diam (lurus) | BIN1 |
| Merah bercorak / berbintik | **DEFECT** | servo membelokkan | BIN2 |
| Warna selain merah | **DEFECT** | servo membelokkan | BIN2 |
| Gagal dibaca | **INVALID** | servo membelokkan (aman) | BIN2 |

## Arsitektur

```
Webcam ──► main.py (Python)
             ├─ vision/        deteksi objek + inspeksi merah  ──► PERFECT / DEFECT
             ├─ communication/ FirebaseSync  ──► /detections, /statistics, /vision, /session
             └─ server/        http://127.0.0.1:8000
                                 ├─ dashboard web (web-dashboard/dist)
                                 ├─ /video_feed  (stream kamera di panel dashboard)
                                 └─ /api/state, /api/control, /api/confirm
Firebase RTDB ◄──► ESP32 (firmware/)  baca /detections, gerakkan SG90,
                                      tulis sortAction + sortedAtMs, heartbeat /conveyor
```

Dashboard tidak memakai Firebase Web SDK. Semua datanya diambil dari `main.py`,
yang mencerminkan isi Firebase (termasuk tulisan ESP32) lewat Admin SDK. Dengan
begitu database tetap tertutup untuk publik.

## Struktur

```
UAS/
├── main.py                      # satu-satunya entry point
├── config.py                    # semua parameter (kamera, ROI, aturan merah, server)
├── camera/camera_manager.py     # capture webcam (thread)
├── vision/
│   ├── pipeline.py              # loop kamera: kalibrasi → deteksi → gate → inspeksi → stream
│   ├── quality_inspector.py     # aturan PERFECT / DEFECT / INVALID
│   ├── red_segmentation.py      # mask merah HSV (2 rentang hue)
│   ├── object_detector.py       # background subtraction
│   ├── background_calibrator.py # median 30 frame belt kosong
│   ├── object_tracker.py        # EventGate: satu event per balok, ID unik
│   ├── roi_manager.py
│   └── inspection_history.py
├── communication/firebase_sync.py
├── server/web_server.py
├── web-dashboard/               # React + Vite (sumber dashboard)
├── firmware/ConveyorSorting_ESP32/
│   ├── ConveyorSorting_ESP32.ino
│   └── secrets.example.h        # salin ke secrets.h
├── firebase/database.rules.json
└── tests/
```

## Menjalankan

### 1. Python

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Build dashboard (sekali, atau setiap kali `web-dashboard/src` diubah)

```powershell
cd web-dashboard
npm install
npm run build
cd ..
```

### 3. Firebase (agar data sampai ke ESP32)

1. Buat Realtime Database di Firebase Console.
2. Salin `.env.example` menjadi `.env`, lalu isi `FIREBASE_DATABASE_URL`.
3. Unduh service-account key (Project settings → Service accounts → Generate new
   private key), simpan sebagai `serviceAccountKey.json` di folder proyek. File ini
   sudah di-ignore git, jadi **jangan dibagikan**.
4. Terapkan isi `firebase/database.rules.json` di tab **Rules** (baca/tulis publik
   ditolak; Python Admin SDK dan ESP32 yang memakai database secret tetap bisa).

Tanpa langkah ini sistem tetap berjalan dalam mode lokal: kamera, inspeksi, dan
dashboard bekerja, tetapi ESP32 tidak menerima data.

### 4. Jalankan sistem

```powershell
python main.py
```

Browser terbuka ke `http://127.0.0.1:8000`. Kamera langsung menyala lalu
mengkalibrasi latar belakang, jadi **kosongkan conveyor selama kalibrasi**.
Tombol Start/Stop, Recalibrate, dan Debug ada di panel kamera. Hentikan dengan `Ctrl+C`.

Opsi: `python main.py --no-browser --port 8000 --host 0.0.0.0` (pakai `0.0.0.0`
agar dashboard bisa dibuka dari perangkat lain di jaringan yang sama).

### 5. ESP32

1. Arduino IDE: pasang board **esp32 by Espressif**, library **ArduinoJson (v7)**
   dan **ESP32Servo**.
2. Salin `firmware/ConveyorSorting_ESP32/secrets.example.h` menjadi `secrets.h`,
   lalu isi Wi-Fi, URL database, dan *database secret*.
   Jika `FIREBASE_AUTH` dibiarkan kosong, ESP32 hanya bisa mengakses database
   selama rules masih terbuka. Setelah `firebase/database.rules.json` dipasang,
   ESP32 akan mendapat 401 sampai database secret diisi.
3. Ukur waktu tempuh balok dari tengah ROI kamera ke lengan servo (uji U3), lalu
   isi `TRAVEL_TIME_MS` (t = L / v). Nilai servo (`HOME_ANGLE` 90°, `DIVERT_ANGLE`
   180°, pulsa 1000–2000 µs, tahan 700 ms, kembali 500 ms) diambil dari firmware
   serial lama yang sudah diuji di bench. Tetap periksa saat uji U4.
4. Upload. Serial Monitor 115200 menampilkan event, aksi servo, dan status Wi-Fi.

Servo diberi daya dari buck 5 V tersendiri, GND disatukan dengan ESP32, dan sinyal
dihubungkan ke GPIO 18. ESP32 dan PC harus tersinkron NTP (Windows: *Settings →
Time → Sync now*), karena waktu servo dihitung dari `detectedAtMs` yang dikirim PC.

## Aturan inspeksi (config.py)

Balok **PERFECT** hanya jika kedua syarat ini terpenuhi:

* `red_coverage >= RED_COVERAGE_THRESHOLD` (default 0.98), dan
* tidak ada area non-merah yang tersambung seluas `DEFECT_MIN_BLOB_AREA` piksel
  atau lebih (default 40). Inilah yang menangkap corak/bintik kecil.

Mask objek dikecilkan `MASK_ERODE_PX` piksel agar tepi, bayangan, dan belt tidak
ikut terhitung. Ketiga nilai ini perlu disetel dengan balok asli di bawah
pencahayaan uji: aktifkan **Debug** di dashboard, lalu lihat `red_coverage` dan
`largestDefectArea` setiap event.

## Data Firebase

| Path | Ditulis oleh | Isi |
|---|---|---|
| `/session` | Python | `id, status, startedAtMs, stoppedAtMs` |
| `/vision` | Python | `status, lastClass, lastEventId, lastDetectionMs, redCoverage` |
| `/detections/{eventId}` | Python | `class, redCoverage, redPixels, objectPixels, nonRedPixels, largestDefectArea, detectedAtMs, sessionId, timestamp` |
| | ESP32 | `sortAction (STRAIGHT/DIVERT/MISSED), sortedAtMs` |
| | Operator (dashboard) | `actualBin (BIN1/BIN2), confirmedAtMs` |
| `/statistics` | Python | `total, perfect, defect, invalid` |
| `/conveyor` | ESP32 | `deviceOnline, lastHeartbeatMs, servoState, queueLength, wifiRssi` |

`eventId` berurutan menurut waktu (`OBJ-<yymmddHHMMSS><hex>-<seq>`). Karena itu
ESP32 cukup membaca 5 event terbaru (`orderBy="$key"&limitToLast=5`).

## Indikator kinerja (dihitung di dashboard per sesi)

* **Cycle time** = `sortedAtMs − detectedAtMs` (dari deteksi kamera sampai servo
  kembali ke posisi lurus), dirata-rata.
* **Production rate** = jumlah objek pada sesi / lama sesi (objek per menit).
* **Sorting accuracy** = event yang wadah aktualnya benar / event yang sudah
  dikonfirmasi operator. Klik **BIN1/BIN2** di tabel riwayat sesuai wadah tempat
  balok benar-benar jatuh.

## Test

```powershell
python -m unittest discover -s tests -t .
```

Test tidak membutuhkan webcam, Firebase, atau ESP32. Kamera dan database diganti
versi palsu, sedangkan server dashboard dan stream kamera ikut diuji.

## Keterbatasan yang diketahui

* Firmware belum dikompilasi atau diuji pada ESP32 fisik di laptop pengembang.
* Jika dua balok terdeteksi lebih cepat dari selang polling ESP32 (~0,4 s), keduanya
  tetap terbaca (5 event terbaru), tetapi jarak antarbalok harus cukup agar servo
  sempat kembali (uji U5).
* `secureClient.setInsecure()` di ESP32: sertifikat HTTPS tidak diverifikasi (cukup untuk prototipe).
* Folder `dataset/green` dan `dataset/non_green` berasal dari rancangan lama (hijau)
  dan tidak dipakai oleh aturan merah.
