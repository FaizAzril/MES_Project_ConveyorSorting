
import cv2
import numpy as np


def main():
    # Membuka kamera laptop
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("ERROR: Kamera tidak dapat dibuka.")
        return

    # Rentang warna hijau dalam HSV
    lower_green = np.array([35, 50, 50])
    upper_green = np.array([85, 255, 255])

    # Kernel untuk mengurangi noise
    kernel = np.ones((5, 5), np.uint8)

    print("Deteksi warna hijau aktif!")
    print("Arahkan objek hijau ke kamera.")
    print("Tekan Q untuk keluar.")

    try:
        while True:
            success, frame = cap.read()

            if not success:
                print("Gagal mengambil gambar.")
                break

            # Konversi gambar dari BGR ke HSV
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

            # Memisahkan area yang masuk rentang hijau
            mask = cv2.inRange(
                hsv,
                lower_green,
                upper_green
            )

            # Mengurangi noise pada hasil deteksi
            mask = cv2.morphologyEx(
                mask, cv2.MORPH_OPEN, kernel
            )
            mask = cv2.morphologyEx(
                mask, cv2.MORPH_CLOSE, kernel
            )

            # Mencari kontur area hijau
            contours, _ = cv2.findContours(
                mask,
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE
            )

            green_detected = False

            for contour in contours:
                area = cv2.contourArea(contour)

                # Abaikan area kecil yang kemungkinan noise
                if area < 800:
                    continue

                green_detected = True

                x, y, w, h = cv2.boundingRect(contour)

                # Gambar kotak di sekitar area hijau
                cv2.rectangle(
                    frame,
                    (x, y),
                    (x + w, y + h),
                    (0, 255, 0),
                    2
                )

                cv2.putText(
                    frame,
                    f"Green - Area: {int(area)}",
                    (x, max(y - 10, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2
                )

            # Status deteksi
            status = (
                "GREEN DETECTED"
                if green_detected
                else "NO GREEN DETECTED"
            )

            color = (
                (0, 255, 0)
                if green_detected
                else (0, 0, 255)
            )

            cv2.putText(
                frame,
                status,
                (15, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                color,
                2
            )

            # Tampilkan hasil
            cv2.imshow("Green Color Detection", frame)
            cv2.imshow("HSV Mask", mask)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("Program selesai.")


if __name__ == "__main__":
    main()
