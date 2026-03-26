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
#define STYLUS_GRIPPER_ANGLE 68 // gentle pen hold

// --- Motion ---
#define STEP_DELAY_MS 15   // delay per degree step (increase for slower motion)
#define LINE_STEP     10   // degrees per "line forward/backward" step
#define STYLUS_BASE_STEP      3
#define STYLUS_SHOULDER_STEP  2
#define STYLUS_ELBOW_COMP     1

#define EEPROM_DRAW_MAGIC      0xAB
#define EEPROM_DRAW_ADDR       0
#define EEPROM_STYLUS_MAGIC    0x5C
#define EEPROM_STYLUS_ADDR     16

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
bool stylusMode = false;

// Saved "pen on paper" pose (calibrated by user). Persisted in EEPROM.
int drawBase = 90, drawShoulder = 90, drawElbow = 90, drawWrist = 90, drawWristRot = 90;
// Saved "stylus touching iPad" pose for 8-way drawing. Persisted in EEPROM.
int stylusTouchBase = 90, stylusTouchShoulder = 90, stylusTouchElbow = 90, stylusTouchWrist = 90, stylusTouchWristRot = 90, stylusTouchGripper = STYLUS_GRIPPER_ANGLE;

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
  int targetBase = b;
  int targetShoulder = sh;
  int targetElbow = e;
  int targetWrist = w;
  int targetWristRot = wr;
  int targetGripper = g;
  clamp(targetBase, BASE_MIN, BASE_MAX);
  clamp(targetShoulder, SHOULDER_MIN, SHOULDER_MAX);
  clamp(targetElbow, ELBOW_MIN, ELBOW_MAX);
  clamp(targetWrist, WRIST_MIN, WRIST_MAX);
  clamp(targetWristRot, WRIST_ROT_MIN, WRIST_ROT_MAX);
  clamp(targetGripper, GRIPPER_MIN, GRIPPER_MAX);

  writeServo(servoBase,      posBase,      targetBase,      BASE_MIN,      BASE_MAX);
  writeServo(servoShoulder,  posShoulder,  targetShoulder,  SHOULDER_MIN,  SHOULDER_MAX);
  writeServo(servoElbow,     posElbow,     targetElbow,     ELBOW_MIN,     ELBOW_MAX);
  writeServo(servoWrist,     posWrist,     targetWrist,     WRIST_MIN,     WRIST_MAX);
  writeServo(servoWristRot,  posWristRot,  targetWristRot,  WRIST_ROT_MIN, WRIST_ROT_MAX);
  writeServo(servoGripper,   posGripper,   targetGripper,   GRIPPER_MIN,   GRIPPER_MAX);
  posBase = targetBase;
  posShoulder = targetShoulder;
  posElbow = targetElbow;
  posWrist = targetWrist;
  posWristRot = targetWristRot;
  posGripper = targetGripper;
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
  if (EEPROM.read(EEPROM_DRAW_ADDR) != EEPROM_DRAW_MAGIC) return;
  drawBase      = EEPROM.read(EEPROM_DRAW_ADDR + 1);
  drawShoulder  = EEPROM.read(EEPROM_DRAW_ADDR + 2);
  drawElbow     = EEPROM.read(EEPROM_DRAW_ADDR + 3);
  drawWrist     = EEPROM.read(EEPROM_DRAW_ADDR + 4);
  drawWristRot  = EEPROM.read(EEPROM_DRAW_ADDR + 5);
}

void saveDrawingPose() {
  EEPROM.write(EEPROM_DRAW_ADDR, EEPROM_DRAW_MAGIC);
  EEPROM.write(EEPROM_DRAW_ADDR + 1, drawBase);
  EEPROM.write(EEPROM_DRAW_ADDR + 2, drawShoulder);
  EEPROM.write(EEPROM_DRAW_ADDR + 3, drawElbow);
  EEPROM.write(EEPROM_DRAW_ADDR + 4, drawWrist);
  EEPROM.write(EEPROM_DRAW_ADDR + 5, drawWristRot);
}

void loadStylusConfig() {
  if (EEPROM.read(EEPROM_STYLUS_ADDR) != EEPROM_STYLUS_MAGIC) return;
  stylusTouchBase     = EEPROM.read(EEPROM_STYLUS_ADDR + 1);
  stylusTouchShoulder = EEPROM.read(EEPROM_STYLUS_ADDR + 2);
  stylusTouchElbow    = EEPROM.read(EEPROM_STYLUS_ADDR + 3);
  stylusTouchWrist    = EEPROM.read(EEPROM_STYLUS_ADDR + 4);
  stylusTouchWristRot = EEPROM.read(EEPROM_STYLUS_ADDR + 5);
  stylusTouchGripper  = EEPROM.read(EEPROM_STYLUS_ADDR + 6);
  stylusMode          = EEPROM.read(EEPROM_STYLUS_ADDR + 7) == 1;
}

void saveStylusConfig() {
  EEPROM.write(EEPROM_STYLUS_ADDR, EEPROM_STYLUS_MAGIC);
  EEPROM.write(EEPROM_STYLUS_ADDR + 1, stylusTouchBase);
  EEPROM.write(EEPROM_STYLUS_ADDR + 2, stylusTouchShoulder);
  EEPROM.write(EEPROM_STYLUS_ADDR + 3, stylusTouchElbow);
  EEPROM.write(EEPROM_STYLUS_ADDR + 4, stylusTouchWrist);
  EEPROM.write(EEPROM_STYLUS_ADDR + 5, stylusTouchWristRot);
  EEPROM.write(EEPROM_STYLUS_ADDR + 6, stylusTouchGripper);
  EEPROM.write(EEPROM_STYLUS_ADDR + 7, stylusMode ? 1 : 0);
}

void setStylusMode(bool enabled) {
  stylusMode = enabled;
  if (stylusMode) {
    moveTo(posBase, posShoulder, posElbow, posWrist, posWristRot, STYLUS_GRIPPER_ANGLE);
    Serial.println(F("Stylus mode ON"));
  } else {
    Serial.println(F("Stylus mode OFF (claw mode)"));
  }
  saveStylusConfig();
}

void saveStylusTouchPose() {
  stylusTouchBase = posBase;
  stylusTouchShoulder = posShoulder;
  stylusTouchElbow = posElbow;
  stylusTouchWrist = posWrist;
  stylusTouchWristRot = posWristRot;
  stylusTouchGripper = posGripper;
  saveStylusConfig();
}

void stylusStep(int dx, int dy) {
  int targetBase = posBase + (dx * STYLUS_BASE_STEP);
  int targetShoulder = posShoulder - (dy * STYLUS_SHOULDER_STEP);
  int targetElbow = posElbow + (dy * STYLUS_ELBOW_COMP);
  moveTo(targetBase, targetShoulder, targetElbow, posWrist, posWristRot, posGripper);
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
  loadStylusConfig();

  Serial.println(F("Adeept 5 DOF Arm ready"));
  Serial.println(F("Pen calibration: p=stylus mode, move tip to iPad, x=save touch home, z=go touch home"));
  Serial.println(F("Stylus drawing: 8=N 9=NE 6=E 3=SE 2=S 1=SW 4=W 7=NW"));
  Serial.println(F("Commands: h=home, b/n=base, u/l=shoulder, e/t=elbow, p/k=stylus/claw, x/z=touch home, s/g/f/v=draw pose, j=draw J, d=demo, o/c=gripper"));
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
      case 'p':
      case 'P':
        setStylusMode(true);
        break;
      case 'k':
      case 'K':
        setStylusMode(false);
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
      case 'x':
      case 'X':
        if (!stylusMode) {
          Serial.println(F("Enable stylus mode first (p)."));
          break;
        }
        saveStylusTouchPose();
        Serial.println(F("Stylus touch home saved."));
        break;
      case 'z':
      case 'Z':
        moveTo(stylusTouchBase, stylusTouchShoulder, stylusTouchElbow, stylusTouchWrist, stylusTouchWristRot, stylusTouchGripper);
        Serial.println(F("At stylus touch home."));
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
      case '8':
        if (!stylusMode) {
          Serial.println(F("Enable stylus mode first (p)."));
          break;
        }
        stylusStep(0, 1);
        Serial.println(F("Stylus north"));
        break;
      case '9':
        if (!stylusMode) {
          Serial.println(F("Enable stylus mode first (p)."));
          break;
        }
        stylusStep(1, 1);
        Serial.println(F("Stylus north-east"));
        break;
      case '6':
        if (!stylusMode) {
          Serial.println(F("Enable stylus mode first (p)."));
          break;
        }
        stylusStep(1, 0);
        Serial.println(F("Stylus east"));
        break;
      case '3':
        if (!stylusMode) {
          Serial.println(F("Enable stylus mode first (p)."));
          break;
        }
        stylusStep(1, -1);
        Serial.println(F("Stylus south-east"));
        break;
      case '2':
        if (!stylusMode) {
          Serial.println(F("Enable stylus mode first (p)."));
          break;
        }
        stylusStep(0, -1);
        Serial.println(F("Stylus south"));
        break;
      case '1':
        if (!stylusMode) {
          Serial.println(F("Enable stylus mode first (p)."));
          break;
        }
        stylusStep(-1, -1);
        Serial.println(F("Stylus south-west"));
        break;
      case '4':
        if (!stylusMode) {
          Serial.println(F("Enable stylus mode first (p)."));
          break;
        }
        stylusStep(-1, 0);
        Serial.println(F("Stylus west"));
        break;
      case '7':
        if (!stylusMode) {
          Serial.println(F("Enable stylus mode first (p)."));
          break;
        }
        stylusStep(-1, 1);
        Serial.println(F("Stylus north-west"));
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
