# adeept-robot

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

| Key | Action |
|-----|--------|
| `h` | Home position |
| `d` | Demo sequence |
| `o` / `c` | Open / close gripper |
| `p` / `k` | Stylus mode ON / claw mode ON |
| `x` | Save current pose as stylus **touch-home** (tip touching iPad) |
| `z` | Move to saved stylus touch-home |
| `s` | Save current drawing pose |
| `g` | Move to saved drawing pose |
| `f` / `v` | Drawing line forward / backward |
| `j` | Draw letter J (paper) |
| `8` `9` `6` `3` `2` `1` `4` `7` | Stylus N / NE / E / SE / S / SW / W / NW step |

Open Serial Monitor at 9600 baud (e.g. `arduino-cli monitor -p /dev/cu.usbmodem* -c baudrate=9600`) and type these keys.

## Stylus calibration workflow (iPad drawing)

Use this once after mounting the stylus attachment:

1. Send `p` to enable stylus mode (firmware applies stylus grip angle).
2. Jog arm with `b/n/u/l/e/t` until stylus just touches the iPad surface.
3. Send `x` to save this contact pose as stylus touch-home.
4. Send `z` any time to return to touch-home before drawing.
5. Use `8/9/6/3/2/1/4/7` for 8-direction in-contact drawing steps.

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

## Camera -> arm tracking (green stylus marker)

This script detects a green marker and sends movement commands to the arm over serial:

- `--direction-mode axis` (default): sends `b/n/u/l`
- `--direction-mode 8way`: sends `8/9/6/3/2/1/4/7` for stylus drawing moves
- Tracking uses **frame agreement** and a **reverse-direction guard** to reduce jitter from noisy vision (tune `--stable-frames` and `--reverse-guard-ms`).

1) Find board port:

```bash
arduino-cli board list
```

2) Run tracker (replace port with yours):

```bash
source .venv/bin/activate
python3 camera_track_arm.py --port /dev/cu.usbserial-2130
```

For stylus drawing on iPad (enable stylus and move to touch-home at start):

```bash
python3 camera_track_arm.py --port /dev/cu.usbserial-2130 --direction-mode 8way --stylus-start
```

Natural-language chat (type requests in the **same terminal** while the OpenCV window is open):

```bash
python3 camera_track_arm.py --port /dev/cu.usbserial-2130 --bot-chat
```

Example prompts:

- `draw the letter j with a single line`
- `can you draw the letter a?`
- `do we have a good live feed?`
- `help`

Optional voice replies (requires `pyttsx3`):

```bash
python3 camera_track_arm.py --port /dev/cu.usbserial-2130 --bot-chat --voice
```

Tracker controls (while camera window is focused):

- `q` quit
- `h` home / neutral
- `o` / `c` open / close gripper
- `p` / `k` stylus mode / claw mode
- `x` save stylus touch-home, `z` go to stylus touch-home
- Arrow keys or `WASD`: jog shoulder/base
- `e` / `t`: elbow out / in
- `8/9/6/3/2/1/4/7`: send direct 8-way stylus commands
- In `--bot-chat` mode, type `quit` or `exit` in the terminal to end chat and tracking.

Useful tuning examples:

```bash
# Different camera index
python3 camera_track_arm.py --port /dev/cu.usbserial-2130 --camera 1

# Slower command rate + larger deadzone (less jitter)
python3 camera_track_arm.py --port /dev/cu.usbserial-2130 --interval-ms 300 --deadzone 70

# Require more agreeing frames before moving + longer pause before reversing
python3 camera_track_arm.py --port /dev/cu.usbserial-2130 --stable-frames 5 --reverse-guard-ms 700

# 8-way stylus direction output + stylus startup sequence
python3 camera_track_arm.py --port /dev/cu.usbserial-2130 --direction-mode 8way --stylus-start
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
