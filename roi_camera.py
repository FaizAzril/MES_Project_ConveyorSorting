
import cv2


def main():
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("ERROR: Kamera tidak dapat dibuka.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    print("ROI Camera aktif.")
    print("Letakkan objek di dalam kotak.")
    print("Tekan Q untuk keluar.")

    try:
        while True:
            success, frame = cap.read()

            if not success:
                print("Gagal membaca frame kamera.")
                break

            height, width = frame.shape[:2]

            # Tentukan area ROI di tengah gambar.
            # Nilai menggunakan persentase ukuran frame.
            x1 = int(width * 0.25)
            x2 = int(width * 0.75)
            y1 = int(height * 0.20)
            y2 = int(height * 0.80)

            # Ambil gambar hanya dari area ROI.
            roi = frame[y1:y2, x1:x2]

            # Gambar pembatas ROI pada video asli.
            display = frame.copy()

            cv2.rectangle(
                display,
                (x1, y1),
                (x2, y2),
                (0, 255, 0),
                2
            )

            cv2.putText(
                display,
                "OBJECT DETECTION AREA",
                (x1, max(y1 - 10, 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                2
            )

            cv2.imshow("Camera - ROI", display)
            cv2.imshow("ROI Preview", roi)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("Program selesai.")


if __name__ == "__main__":
    main()
