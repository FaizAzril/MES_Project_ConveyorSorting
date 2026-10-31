
import cv2


def main():
    # Kamera laptop biasanya menggunakan index 0
    camera_index = 0

    # Coba buka kamera menggunakan backend Windows
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)

    # Jika gagal, coba backend default
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(camera_index)

    if not cap.isOpened():
        print("ERROR: Kamera tidak dapat dibuka.")
        print("Periksa izin kamera atau coba index kamera lain.")
        return

    # Resolusi awal untuk pengujian
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    print("Kamera berhasil dibuka!")
    print("Tekan Q pada jendela kamera untuk keluar.")

    try:
        while True:
            # Ambil satu frame dari kamera
            success, frame = cap.read()

            if not success:
                print("Gagal membaca frame dari kamera.")
                break

            # Tambahkan informasi pada tampilan
            cv2.putText(
                frame,
                "CONVEYOR CV - CAMERA TEST",
                (15, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2
            )

            cv2.putText(
                frame,
                "Press Q to quit",
                (15, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1
            )

            # Tampilkan video real-time
            cv2.imshow("Computer Vision - Laptop Camera", frame)

            # Tekan Q untuk menghentikan program
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        # Bebaskan kamera dan tutup semua jendela
        cap.release()
        cv2.destroyAllWindows()
        print("Program selesai.")


if __name__ == "__main__":
    main()
