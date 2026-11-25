# MES Conveyor Sorting — Web Dashboard

Sumber React untuk dashboard yang disajikan oleh `main.py`. Dashboard ini tidak
terhubung langsung ke Firebase: semua data, video kamera, dan tombol kontrol
lewat server Python lokal (`/api/state`, `/video_feed`, `/api/control`,
`/api/confirm`).

## Build (dipakai oleh `python main.py`)

```powershell
npm install
npm run build
```

Hasilnya `dist/`, disajikan di `http://127.0.0.1:8765`.

## Mode pengembangan

Jalankan `python main.py --no-browser` di folder proyek, lalu di folder ini:

```powershell
npm run dev
```

Buka `http://localhost:5173`. Vite meneruskan `/api` dan `/video_feed` ke port 8765.
