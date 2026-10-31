
import cv2
import numpy as np


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

    background = None

    # Pengaturan awal, dapat disesuaikan nanti
    threshold_value = 30
    min_area = 700
    kernel = np.ones((5, 5), np.uint8)

    print("OBJECT DETECTION")
    print("Kosongkan area ROI, lalu tekan B untuk mengambil background.")
    print("Letakkan objek di ROI untuk menguji deteksi.")
    print("Tekan R untuk mengambil ulang background.")
    print("Tekan Q untuk keluar.")

    try:
        while True:
            success, frame = cap.read()

            if not success:
                print("Gagal membaca kamera.")
                break

            height, width = frame.shape[:2]

            # Area pengamatan di tengah frame
            x1 = int(width * 0.25)
            x2 = int(width * 0.75)
            y1 = int(height * 0.20)
            y2 = int(height * 0.80)

            roi = frame[y1:y2, x1:x2]

            # Kurangi noise sebelum membandingkan gambar
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (5, 5), 0)

            display = frame.copy()
            detected = False
            mask = np.zeros(gray.shape, dtype=np.uint8)

            if background is not None:
                # Bandingkan dengan background saat area kosong
                difference = cv2.absdiff(background, gray)

                _, mask = cv2.threshold(
                    difference,
                    threshold_value,
                    255,
                    cv2.THRESH_BINARY
                )

                # Bersihkan noise kecil
                mask = cv2.morphologyEx(
                    mask, cv2.MORPH_OPEN, kernel
                )
                mask = cv2.morphologyEx(
                    mask, cv2.MORPH_CLOSE, kernel
                )

                contours, _ = cv2.findContours(
                    mask,
                    cv2.RETR_EXTERNAL,
                    cv2.CHAIN_APPROX_SIMPLE
                )

                for contour in contours:
                    area = cv2.contourArea(contour)

                    if area < min_area:
                        continue

                    detected = True

                    # Koordinat kontur relatif terhadap ROI
                    x, y, w, h = cv2.boundingRect(contour)

                    # Ubah menjadi koordinat frame asli
                    cv2.rectangle(
                        display,
                        (x1 + x, y1 + y),
                        (x1 + x + w, y1 + y + h),
                        (0, 255, 0),
                        2
                    )

                status = (
                    "OBJECT DETECTED"
                    if detected
                    else "NO OBJECT DETECTED"
                )

                status_color = (
                    (0, 255, 0)
                    if detected
                    else (0, 0, 255)
                )
            else:
                status = "EMPTY ROI, PRESS B"
                status_color = (0, 255, 255)

            # Tampilkan batas ROI
            cv2.rectangle(
                display,
                (x1, y1),
                (x2, y2),
                (255, 200, 0),
                2
            )

            cv2.putText(
                display,
                status,
                (15, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                status_color,
                2
            )

            cv2.imshow("Object Detection", display)

            if background is not None:
                cv2.imshow("Difference Mask", mask)

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                break
            elif key == ord("b") or key == ord("r"):
                background = gray.copy()
                print("Background berhasil diperbarui.")

    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("Program selesai.")


if __name__ == "__main__":
    main()
