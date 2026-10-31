
import cv2
from pathlib import Path

# Folder proyek dan lokasi penyimpanan dataset
BASE_DIR = Path(__file__).resolve().parent
DATASET_DIR = BASE_DIR / "dataset"

CLASSES = {
    ord("g"): "green",
    ord("n"): "non_green",
}

for class_name in CLASSES.values():
    (DATASET_DIR / class_name).mkdir(
        parents=True, exist_ok=True
    )


def count_images(folder):
    return len(list(folder.glob("*.jpg")))


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

    green_dir = DATASET_DIR / "green"
    non_green_dir = DATASET_DIR / "non_green"

    print("Dataset collector aktif.")
    print("G = simpan gambar GREEN")
    print("N = simpan gambar NON_GREEN")
    print("Q = keluar")

    try:
        while True:
            success, frame = cap.read()

            if not success:
                print("Gagal membaca kamera.")
                break

            height, width = frame.shape[:2]

            # Area tengah untuk meletakkan objek.
            # Gunakan kotak ini sebagai area pengambilan gambar.
            roi_size = min(280, width, height)
            x1 = (width - roi_size) // 2
            y1 = (height - roi_size) // 2
            x2 = x1 + roi_size
            y2 = y1 + roi_size

            # Tampilkan kotak ROI pada salinan frame.
            display = frame.copy()
            cv2.rectangle(
                display,
                (x1, y1),
                (x2, y2),
                (255, 200, 0),
                2
            )

            green_count = count_images(green_dir)
            non_green_count = count_images(non_green_dir)

            cv2.putText(
                display,
                "G: GREEN | N: NON_GREEN | Q: QUIT",
                (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 255),
                2
            )

            cv2.putText(
                display,
                f"Green: {green_count} | Non-green: {non_green_count}",
                (10, 55),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2
            )

            cv2.imshow("Dataset Collector", display)

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                break

            if key in CLASSES:
                class_name = CLASSES[key]
                output_dir = DATASET_DIR / class_name

                # Ambil gambar asli di dalam ROI,
                # bukan frame yang sudah diberi teks.
                crop = frame[y1:y2, x1:x2]

                # Samakan ukuran dasar gambar untuk dataset.
                image = cv2.resize(crop, (224, 224))

                image_count = count_images(output_dir) + 1
                filename = (
                    f"{class_name}_{image_count:04d}.jpg"
                )
                output_path = output_dir / filename

                saved = cv2.imwrite(
                    str(output_path), image
                )

                if saved:
                    print(f"Tersimpan: {output_path}")
                else:
                    print("Gagal menyimpan gambar.")

    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("Pengumpulan dataset selesai.")


if __name__ == "__main__":
    main()
