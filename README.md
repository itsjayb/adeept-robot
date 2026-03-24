# Adeept 5 DOF Robotic Arm

Arduino sketch and scripts to run the **Adeept 5 DOF Robotic Arm** from the command line (arduino-cli). Compatible with Arduino UNO R3 and the Adeept Robotic Arm Driver Board (ATMEGA328P).

## Wiring (driver board)

| Servo        | Function       | Arduino pin |
|-------------|----------------|-------------|
| Servo 1     | Base rotation  | D3          |
| Servo 2     | Shoulder       | D5          |
| Servo 3     | Elbow          | D6          |
| Servo 4     | Wrist          | D9          |
| Servo 5     | Wrist rotation | D10         |
| Servo 6     | Gripper        | D11         |

If your board uses different pins, edit the `PIN_SERVO_*` defines in `adeept_5dof_arm.ino`.

## Build and upload

From this folder. The script uses your Arduino IDE libraries (`~/Library/Arduino15`) so the Servo library is found.

```bash
# Compile only
./build.sh

# Compile and upload (auto-detect USB port)
./build.sh upload

# Compile and upload to a specific port
./build.sh upload /dev/cu.usbmodem010NTLEGE0322
```

Or with arduino-cli directly:

```bash
arduino-cli compile --fqbn arduino:avr:uno .
arduino-cli upload -p /dev/cu.usbmodem* --fqbn arduino:avr:uno .
```

List ports: `arduino-cli board list`

## Serial commands (9600 baud)

| Key | Action        |
|-----|---------------|
| `h` | Home position |
| `d` | Demo sequence |
| `o` | Open gripper  |
| `c` | Close gripper |

Open Serial Monitor at 9600 baud (e.g. `arduino-cli monitor -p /dev/cu.usbmodem* -c baudrate=9600`) and type these keys.

## Tuning

- **Speed**: Increase `STEP_DELAY_MS` in the sketch for slower, smoother motion.
- **Limits**: Adjust `*_MIN` and `*_MAX` for each servo to match your arm and avoid mechanical limits.

## Camera live view (first integration step)

Use this to verify your camera feed before connecting vision to arm movement.

```bash
# 1) (recommended) create a virtual env
python3 -m venv .venv
source .venv/bin/activate

# 2) install OpenCV
pip install -r requirements-camera.txt

# 3) open camera view
python3 camera_view.py
```

Controls:

- Press `q` to quit.
- Press `s` to save a snapshot to `snapshots/`.

If the window does not open, try another camera index:

```bash
python3 camera_view.py --camera 1
python3 camera_view.py --camera 2
```

## Camera -> arm tracking (green object)

This script detects a green object and sends movement commands to the arm over serial:

- left/right target offset -> base rotate (`b` / `n`)
- up/down target offset -> shoulder move (`u` / `l`)

1) Find board port:

```bash
arduino-cli board list
```

2) Run tracker (replace port with yours):

```bash
source .venv/bin/activate
python3 camera_track_arm.py --port /dev/cu.usbserial-2130
```

Tracker controls:

- `q` quit
- `h` or `0` — **home / neutral** (Arduino moves all joints to ~90° and gripper closed — that is the sketch’s “start pose”, not literal 0° servo PWM)
- `o` open gripper
- `c` close gripper
- `m` toggle auto-tracking on/off (**auto starts OFF** so the arm won’t move until you press `m`)

Manual movement keys (while camera window is focused):

- `a` base left
- `d` base right
- `w` shoulder up
- `s` shoulder down
- `r` elbow out
- `f` elbow in

Useful tuning examples:

```bash
# Different camera index
python3 camera_track_arm.py --port /dev/cu.usbserial-2130 --camera 1

# Slower command rate + larger deadzone (less jitter)
python3 camera_track_arm.py --port /dev/cu.usbserial-2130 --interval-ms 300 --deadzone 70

# Stronger smoothing + hold last target when blob vanishes briefly (reduces flicker)
python3 camera_track_arm.py --port /dev/cu.usbserial-2130 --ema 0.2 --lost-hold-ms 400

# Old behavior: auto-tracking ON as soon as the app starts
python3 camera_track_arm.py --port /dev/cu.usbserial-2130 --auto-start
```

## Upload: "programmer is not responding" / "not in sync: resp=0x00"

If upload fails with sync errors:

1. **Try the other port** – You may have two USB serial devices. List them: `arduino-cli board list`. Then try:
   ```bash
   ./build.sh upload /dev/cu.usbserial-2130
   # or
   ./build.sh upload /dev/cu.usbmodem010NTLEGE0322
   ```
   (Use the port that appears when you plug in the **Adeept board** only.)

2. **Press RESET** – As soon as you run `./build.sh upload`, press the RESET button on the Adeept/Arduino board once. Some clones need this to enter the bootloader.

3. **Free the port** – Close Serial Monitor, other terminal sessions, or any app using the same USB port, then upload again.

4. **Cable and power** – Use a data-capable USB cable (not charge-only). If possible, plug the board directly into the Mac.

## Resources

- [Adeept learn page](https://www.adeept.com/learn/detail-64.html) – official ZIP with full code and docs
- Select **Arduino UNO R3** as the board in Arduino IDE / arduino-cli
