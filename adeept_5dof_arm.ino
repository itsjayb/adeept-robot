/*
 * Adeept 5 DOF Robotic Arm
 * Compatible with Arduino UNO R3 / Adeept Robotic Arm Driver Board (ATMEGA328P)
 *
 * Servos: 5 joints + gripper (6 servos total)
 * Pins match common Adeept driver board: D3, D5, D6, D9, D10, D11 (PWM)
 * If your board uses different pins, change the PIN_* defines below.
 */

#include <Servo.h>
#include <EEPROM.h>

// --- Servo pins (change if your driver board uses different pins) ---
#define PIN_SERVO_BASE    3   // Servo 1: base rotation
#define PIN_SERVO_SHOULDER 5  // Servo 2: shoulder
#define PIN_SERVO_ELBOW    6  // Servo 3: elbow
#define PIN_SERVO_WRIST    9  // Servo 4: wrist pitch
#define PIN_SERVO_WRIST_ROT 10 // Servo 5: wrist rotation
#define PIN_SERVO_GRIPPER  11  // Servo 6: gripper

// --- Safe angle limits (adjust for your arm to avoid mechanical damage) ---
#define MIN_ANGLE 0
#define MAX_ANGLE 180

#define BASE_MIN      0
#define BASE_MAX      180
#define SHOULDER_MIN  30
#define SHOULDER_MAX  150
#define ELBOW_MIN     20
#define ELBOW_MAX     160
#define WRIST_MIN     0
#define WRIST_MAX     180
#define WRIST_ROT_MIN 0
#define WRIST_ROT_MAX 180
#define GRIPPER_MIN   60   // closed
#define GRIPPER_MAX   120  // open

// --- Motion ---
#define STEP_DELAY_MS 15   // delay per degree step (increase for slower motion)
#define LINE_STEP     10   // degrees per "line forward/backward" step
#define EEPROM_MAGIC  0xAB
#define EEPROM_ADDR  0

Servo servoBase;
Servo servoShoulder;
Servo servoElbow;
Servo servoWrist;
Servo servoWristRot;
Servo servoGripper;

int posBase = 90;
int posShoulder = 90;
int posElbow = 90;
int posWrist = 90;
int posWristRot = 90;
int posGripper = GRIPPER_MIN;

// Saved "pen on paper" pose (calibrated by user). Persisted in EEPROM.
int drawBase = 90, drawShoulder = 90, drawElbow = 90, drawWrist = 90, drawWristRot = 90;

void clamp(int& val, int lo, int hi) {
  if (val < lo) val = lo;
  if (val > hi) val = hi;
}

void writeServo(Servo& s, int current, int target, int minA, int maxA) {
  clamp(target, minA, maxA);
  while (current != target) {
    if (current < target) current++;
    else current--;
    s.write(current);
    delay(STEP_DELAY_MS);
  }
}

void moveTo(int b, int sh, int e, int w, int wr, int g) {
  writeServo(servoBase,      posBase,      b,  BASE_MIN,      BASE_MAX);
  writeServo(servoShoulder,  posShoulder,  sh, SHOULDER_MIN,  SHOULDER_MAX);
  writeServo(servoElbow,     posElbow,     e,  ELBOW_MIN,     ELBOW_MAX);
  writeServo(servoWrist,     posWrist,     w,  WRIST_MIN,     WRIST_MAX);
  writeServo(servoWristRot,  posWristRot,  wr, WRIST_ROT_MIN, WRIST_ROT_MAX);
  writeServo(servoGripper,   posGripper,   g,  GRIPPER_MIN,   GRIPPER_MAX);
  posBase = b;
  posShoulder = sh;
  posElbow = e;
  posWrist = w;
  posWristRot = wr;
  posGripper = g;
}

// Draw letter J on paper. Position arm first so pencil tip is ON the paper, then send 'j'.
// Waypoints keep shoulder/elbow in a tight band so the tip stays at drawing height (not in the air).
void drawJ() {
  const int w = 90, wr = 90, g = GRIPPER_MIN;
  // Flat trajectory: small shoulder/elbow range = tip stays on paper; base sweeps left for J
  moveTo(105, 84, 96, w, wr, g);   // top of J (right)
  moveTo(105, 85, 95, w, wr, g);
  moveTo(105, 86, 94, w, wr, g);   // vertical down
  moveTo(105, 87, 93, w, wr, g);   // bottom of stem
  moveTo(95, 87, 93, w, wr, g);    // curve left
  moveTo(85, 86, 94, w, wr, g);
  moveTo(75, 85, 95, w, wr, g);
  moveTo(65, 84, 96, w, wr, g);    // end of hook
}

void loadDrawingPose() {
  if (EEPROM.read(EEPROM_ADDR) != EEPROM_MAGIC) return;
  drawBase      = EEPROM.read(EEPROM_ADDR + 1);
  drawShoulder  = EEPROM.read(EEPROM_ADDR + 2);
  drawElbow     = EEPROM.read(EEPROM_ADDR + 3);
  drawWrist     = EEPROM.read(EEPROM_ADDR + 4);
  drawWristRot  = EEPROM.read(EEPROM_ADDR + 5);
}

void saveDrawingPose() {
  EEPROM.write(EEPROM_ADDR, EEPROM_MAGIC);
  EEPROM.write(EEPROM_ADDR + 1, drawBase);
  EEPROM.write(EEPROM_ADDR + 2, drawShoulder);
  EEPROM.write(EEPROM_ADDR + 3, drawElbow);
  EEPROM.write(EEPROM_ADDR + 4, drawWrist);
  EEPROM.write(EEPROM_ADDR + 5, drawWristRot);
}

void setup() {
  Serial.begin(9600);

  servoBase.attach(PIN_SERVO_BASE);
  servoShoulder.attach(PIN_SERVO_SHOULDER);
  servoElbow.attach(PIN_SERVO_ELBOW);
  servoWrist.attach(PIN_SERVO_WRIST);
  servoWristRot.attach(PIN_SERVO_WRIST_ROT);
  servoGripper.attach(PIN_SERVO_GRIPPER);

  // Start at neutral pose
  servoBase.write(posBase);
  servoShoulder.write(posShoulder);
  servoElbow.write(posElbow);
  servoWrist.write(posWrist);
  servoWristRot.write(posWristRot);
  servoGripper.write(posGripper);
  delay(500);
  loadDrawingPose();

  Serial.println(F("Adeept 5 DOF Arm ready"));
  Serial.println(F("Pen calibration: move tip to paper, then s=save pose, g=go to pose, f=line fwd, v=line back"));
  Serial.println(F("Commands: h=home, b/n=base, u/l=shoulder, e/t=elbow, s/g/f/v=draw, j=draw J, d=demo, o/c=gripper"));
}

void loop() {
  if (Serial.available()) {
    char cmd = Serial.read();
    switch (cmd) {
      case 'h':
      case 'H':
        moveTo(90, 90, 90, 90, 90, GRIPPER_MIN);
        Serial.println(F("Home"));
        break;
      case 'd':
      case 'D':
        Serial.println(F("Demo"));
        moveTo(90, 90, 90, 90, 90, GRIPPER_MAX);
        delay(300);
        moveTo(60, 60, 120, 90, 90, GRIPPER_MAX);
        delay(300);
        moveTo(120, 120, 60, 90, 90, GRIPPER_MAX);
        delay(300);
        moveTo(90, 90, 90, 90, 90, GRIPPER_MIN);
        break;
      case 'o':
      case 'O':
        moveTo(posBase, posShoulder, posElbow, posWrist, posWristRot, GRIPPER_MAX);
        Serial.println(F("Gripper open"));
        break;
      case 'c':
      case 'C':
        moveTo(posBase, posShoulder, posElbow, posWrist, posWristRot, GRIPPER_MIN);
        Serial.println(F("Gripper close"));
        break;
      case 'u':
      case 'U':
        moveTo(posBase, posShoulder - 15, posElbow, posWrist, posWristRot, posGripper);
        Serial.println(F("Arm up"));
        break;
      case 'l':
      case 'L':
        moveTo(posBase, posShoulder + 15, posElbow, posWrist, posWristRot, posGripper);
        Serial.println(F("Arm down"));
        break;
      case 'b':
      case 'B':
        moveTo(posBase - 15, posShoulder, posElbow, posWrist, posWristRot, posGripper);
        Serial.println(F("Base left"));
        break;
      case 'n':
      case 'N':
        moveTo(posBase + 15, posShoulder, posElbow, posWrist, posWristRot, posGripper);
        Serial.println(F("Base right"));
        break;
      case 'e':
      case 'E':
        moveTo(posBase, posShoulder, posElbow + 15, posWrist, posWristRot, posGripper);
        Serial.println(F("Elbow out"));
        break;
      case 't':
      case 'T':
        moveTo(posBase, posShoulder, posElbow - 15, posWrist, posWristRot, posGripper);
        Serial.println(F("Elbow in"));
        break;
      case 'j':
      case 'J':
        Serial.println(F("Drawing J..."));
        drawJ();
        Serial.println(F("Done"));
        break;
      case 's':
      case 'S':
        drawBase = posBase;
        drawShoulder = posShoulder;
        drawElbow = posElbow;
        drawWrist = posWrist;
        drawWristRot = posWristRot;
        saveDrawingPose();
        Serial.println(F("Drawing pose saved (pen-on-paper). Use g to return, f/v for line."));
        break;
      case 'g':
      case 'G':
        moveTo(drawBase, drawShoulder, drawElbow, drawWrist, drawWristRot, posGripper);
        Serial.println(F("At drawing pose"));
        break;
      case 'f':
      case 'F':
        moveTo(drawBase + LINE_STEP, drawShoulder, drawElbow, drawWrist, drawWristRot, posGripper);
        Serial.println(F("Line forward"));
        break;
      case 'v':
      case 'V':
        moveTo(drawBase - LINE_STEP, drawShoulder, drawElbow, drawWrist, drawWristRot, posGripper);
        Serial.println(F("Line backward"));
        break;
      default:
        break;
    }
  }

  // Optional: run demo once on first loop then idle (comment out to disable)
  // static bool once = true;
  // if (once) { once = false; moveTo(90,90,90,90,90,GRIPPER_MAX); delay(500); moveTo(90,90,90,90,90,GRIPPER_MIN); }

  delay(20);
}
