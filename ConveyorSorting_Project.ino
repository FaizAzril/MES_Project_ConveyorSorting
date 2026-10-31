
#include <ESP32Servo.h>

Servo sortingServo;

const int SERVO_PIN = 18;

void setup() {
  Serial.begin(115200);

  sortingServo.setPeriodHertz(50);
  sortingServo.attach(SERVO_PIN, 600, 2300);

  sortingServo.write(90);

  Serial.println("Servo SG90 Ready");
}

void loop() {
  // Posisi awal
  sortingServo.write(90);
  delay(2000);

  // Bergerak ke kiri
  sortingServo.write(30);
  delay(2000);

  // Kembali ke posisi awal
  sortingServo.write(90);
  delay(2000);

  // Bergerak ke kanan
  sortingServo.write(150);
  delay(2000);
}
