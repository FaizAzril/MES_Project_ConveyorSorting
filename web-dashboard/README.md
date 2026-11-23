# MES Conveyor Sorting — Web Dashboard

Dashboard web React untuk memantau hasil inspeksi dari Firebase Realtime Database. Tampilan dibuat monokrom hitam-putih dan tidak memerlukan login. Dashboard hanya membaca data (read-only); aplikasi Python/Admin SDK tetap menjadi penulis data.

## Menjalankan lokal

1. Salin `.env.example` menjadi `.env.local`.
2. Isi konfigurasi Firebase Web App pada `.env.local`.
3. Atur Realtime Database Rules sesuai bagian keamanan di bawah.
4. Jalankan `npm install` lalu `npm run dev`.

## Firebase Security Rules — tanpa login

Karena web tidak memakai login, pembacaan database harus diizinkan secara publik. Ini berarti siapa pun yang mengetahui URL database dapat membaca seluruh data yang diizinkan oleh rules. Batasi data yang disimpan agar tidak memuat informasi pribadi/rahasia. Web dashboard ini tidak menulis data. Untuk akses publik read-only pada tahap demo, rules dapat menggunakan: \n
```json
{
  "rules": {
    ".read": true,
    ".write": false
  }
}
```

Jangan gunakan rules ini jika database menyimpan data sensitif. Python Firebase Admin SDK dapat menulis melalui kredensial server dan melewati rules; simpan service account key secara privat dan jangan masukkan ke web atau Git.
