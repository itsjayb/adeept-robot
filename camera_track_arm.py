#!/usr/bin/env python3
"""
Track a colored target and steer the Adeept arm over serial.

Default target color is green in HSV space. Tune with CLI flags if needed.
"""

import argparse
from dataclasses import dataclass
import glob
import inspect
import select
import sys
import time
from typing import List, Optional, Sequence, Tuple

import cv2
import serial
import serial.tools.list_ports

from bot_commands import CapabilityContext, evaluate_command


@dataclass
class McuCapabilities:
    supports_stylus_mode: bool = False
    supports_8way: bool = False


SERIAL_TX_COUNT = 0
SERIAL_RX_COUNT = 0
TRACE_SERIAL = False
TRACE_FUNCTIONS = False


def _trace_serial(text: str) -> None:
    if TRACE_SERIAL:
        print(f"[TRACE][SERIAL] {text}")


def _trace_fn(text: str) -> None:
    if TRACE_FUNCTIONS:
        print(f"[TRACE][FLOW] {text}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Camera tracking -> arm serial control")
    parser.add_argument("--camera", type=int, default=0, help="Camera index (default: 0)")
    parser.add_argument(
        "--port",
        required=True,
        help="Serial device path (not the text YOUR_PORT). Example: /dev/cu.usbmodem010NTLEGE0322",
    )
    parser.add_argument("--baud", type=int, default=9600, help="Serial baud (default: 9600)")
    parser.add_argument("--width", type=int, default=640, help="Frame width (default: 640)")
    parser.add_argument("--height", type=int, default=480, help="Frame height (default: 480)")
    parser.add_argument(
        "--deadzone",
        type=int,
        default=50,
        help="Pixels around image center with no movement (default: 50)",
    )
    parser.add_argument(
        "--interval-ms",
        type=int,
        default=220,
        help="Minimum milliseconds between arm commands (default: 220)",
    )
    parser.add_argument(
        "--stable-frames",
        type=int,
        default=3,
        help="Consecutive frames that must agree before sending a move (default: 3)",
    )
    parser.add_argument(
        "--reverse-guard-ms",
        type=int,
        default=500,
        help="Minimum ms before allowing opposite-direction command (default: 500)",
    )
    parser.add_argument("--h-min", type=int, default=40, help="HSV H lower bound")
    parser.add_argument("--s-min", type=int, default=70, help="HSV S lower bound")
    parser.add_argument("--v-min", type=int, default=70, help="HSV V lower bound")
    parser.add_argument("--h-max", type=int, default=85, help="HSV H upper bound")
    parser.add_argument("--s-max", type=int, default=255, help="HSV S upper bound")
    parser.add_argument("--v-max", type=int, default=255, help="HSV V upper bound")
    parser.add_argument(
        "--min-area",
        type=int,
        default=900,
        help="Minimum contour area to accept as target (default: 900)",
    )
    parser.add_argument(
        "--direction-mode",
        choices=("axis", "8way"),
        default="axis",
        help="axis=b/n/u/l (default) or 8way=8/9/6/3/2/1/4/7 stylus drawing commands",
    )
    parser.add_argument(
        "--stylus-start",
        action="store_true",
        help="Send p then z at startup (enable stylus mode and go to stylus touch home)",
    )
    parser.add_argument(
        "--bot-chat",
        action="store_true",
        help="Enable natural-language command chat from terminal input.",
    )
    parser.add_argument(
        "--voice",
        action="store_true",
        help="Speak bot responses (requires pyttsx3).",
    )
    parser.add_argument(
        "--plane-j-attempts",
        type=int,
        default=1,
        help="How many plane-locked J runs per draw command (default: 1). Raise while testing.",
    )
    parser.add_argument(
        "--plane-j-pause-s",
        type=float,
        default=2.5,
        help="Seconds between repeated J runs (default: 2.5).",
    )
    parser.add_argument(
        "--learn-attempts",
        type=int,
        default=None,
        metavar="N",
        help="(Ignored — camera learning was removed. Use --plane-j-attempts for repeat J runs.)",
    )
    parser.add_argument(
        "--learn-target-score",
        type=float,
        default=None,
        metavar="S",
        help="(Ignored — no learning score anymore.)",
    )
    parser.add_argument(
        "--trace-serial",
        action="store_true",
        help="Print every serial TX/RX event for debugging.",
    )
    parser.add_argument(
        "--trace-functions",
        action="store_true",
        help="Print key function-call flow for learning/drawing.",
    )
    parser.add_argument(
        "--serial-warmup-ms",
        type=int,
        default=1800,
        help="Wait this long after opening serial (default: 1800).",
    )
    parser.add_argument(
        "--serial-handshake-timeout-ms",
        type=int,
        default=1500,
        help="Timeout waiting for MCU handshake response (default: 1500).",
    )
    parser.add_argument(
        "--serial-handshake-retries",
        type=int,
        default=3,
        help="Handshake retries before continuing with warning (default: 3).",
    )
    parser.add_argument(
        "--auto-port-scan",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If handshake fails, scan /dev/cu.* ports and switch to a responsive MCU port.",
    )
    parser.add_argument(
        "--require-handshake",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Exit if no responsive MCU is found (default: enabled).",
    )
    return parser.parse_args()


def _serial_port_looks_placeholder(port: str) -> bool:
    p = port.strip().upper().replace(" ", "")
    if not p:
        return True
    if p == "YOUR_PORT" or p.endswith("_PORT") and "YOUR" in p:
        return True
    if p in {"COM?", "TBD", "NONE"}:
        return True
    return False


def send_cmd(ser: serial.Serial, cmd: str) -> None:
    global SERIAL_TX_COUNT
    caller = inspect.currentframe().f_back.f_code.co_name  # type: ignore[union-attr]
    _trace_serial(f"TX #{SERIAL_TX_COUNT + 1} cmd='{cmd}' caller={caller}")
    ser.write(cmd.encode("ascii"))
    SERIAL_TX_COUNT += 1


def drain_serial_messages(ser: serial.Serial, prefix: str = "MCU") -> List[str]:
    """Print all currently available newline-terminated serial messages."""
    global SERIAL_RX_COUNT
    messages: List[str] = []
    try:
        while getattr(ser, "in_waiting", 0) > 0:
            raw = ser.readline()
            if not raw:
                break
            text = raw.decode("utf-8", errors="ignore").strip()
            if text:
                SERIAL_RX_COUNT += 1
                messages.append(text)
                _trace_serial(f"RX #{SERIAL_RX_COUNT} text='{text}'")
                print(f"{prefix}: {text}")
    except serial.SerialException:
        return messages
    return messages


def wait_for_mcu_handshake(
    ser: serial.Serial,
    warmup_ms: int,
    timeout_ms: int,
    retries: int,
) -> bool:
    """Try to confirm MCU responds on serial before runtime loops."""
    _trace_fn(
        f"wait_for_mcu_handshake(warmup_ms={warmup_ms}, timeout_ms={timeout_ms}, retries={retries})"
    )
    time.sleep(max(0.0, warmup_ms / 1000.0))
    try:
        ser.reset_input_buffer()
    except Exception:
        pass
    for attempt in range(1, max(1, retries) + 1):
        print(f"Serial handshake attempt {attempt}/{max(1, retries)}: sending 'h' ping...")
        try:
            send_cmd(ser, "h")
        except serial.SerialException as exc:
            print(f"Serial handshake write failed: {exc}")
            return False
        deadline = time.monotonic() + max(0.1, timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            before = SERIAL_RX_COUNT
            drain_serial_messages(ser, prefix="MCU")
            if SERIAL_RX_COUNT > before:
                print("Serial handshake OK: MCU responded.")
                return True
            time.sleep(0.03)
    print("WARNING: No MCU response during handshake. Commands may not move the arm.")
    return False


def list_candidate_serial_ports() -> List[str]:
    deny_tokens = ("Bluetooth", "debug-console", "Vivitar", "WT01", "BT", "NTLEGE")
    deny_desc_tokens = ("USB Controls",)
    deny_vendor_tokens = ("LG Electronics",)
    out: List[str] = []
    seen = set()

    # Prefer pyserial metadata when available so we can reject known non-arm devices.
    for p in serial.tools.list_ports.comports():
        device = p.device or ""
        desc = (p.description or "").strip()
        manufacturer = (p.manufacturer or "").strip()
        if not device.startswith("/dev/cu."):
            continue
        if any(tok in device for tok in deny_tokens):
            continue
        if any(tok in desc for tok in deny_desc_tokens):
            continue
        if any(tok in manufacturer for tok in deny_vendor_tokens):
            continue
        if device not in seen:
            out.append(device)
            seen.add(device)

    # Fallback to filesystem listing for unusual environments.
    for p in sorted(glob.glob("/dev/cu.*")):
        if p in seen:
            continue
        if any(tok in p for tok in deny_tokens):
            continue
        out.append(p)
        seen.add(p)
    return out


def find_responsive_serial_port(
    baud: int,
    warmup_ms: int,
    timeout_ms: int,
) -> Optional[str]:
    candidates = list_candidate_serial_ports()
    if not candidates:
        print("Serial probe: no candidate /dev/cu.* ports found.")
        return None
    print(f"Serial probe: checking {len(candidates)} candidate port(s)...")
    for port in candidates:
        print(f"Serial probe: testing {port}")
        try:
            test_ser = serial.Serial(port, baud, timeout=0.0)
        except serial.SerialException:
            continue
        try:
            ok = wait_for_mcu_handshake(
                ser=test_ser,
                warmup_ms=min(900, max(250, warmup_ms // 2)),
                timeout_ms=max(300, timeout_ms // 2),
                retries=1,
            )
            if ok:
                print(f"Serial probe: selected {port}")
                return port
        finally:
            try:
                test_ser.close()
            except Exception:
                pass
    print("Serial probe: no responsive MCU port found.")
    return None


def detect_mcu_capabilities(messages: Sequence[str]) -> McuCapabilities:
    joined = "\n".join(messages).lower()
    supports_stylus_mode = any(
        token in joined
        for token in ("stylus", "touch home", "p=stylus", "x=save stylus", "z=go touch")
    )
    supports_8way = any(
        token in joined
        for token in ("stylus drawing", "8=n", "9=ne", "north-east", "north-west", "stylus north")
    )
    # This sketch ships stylus touch home and 8-way drawing together; boot text can be missed if serial opens late.
    if supports_stylus_mode and not supports_8way:
        supports_8way = True
    return McuCapabilities(
        supports_stylus_mode=supports_stylus_mode,
        supports_8way=supports_8way,
    )


def manual_move_command(key: int) -> Optional[str]:
    """Map keyboard to the same single-char jog commands the firmware uses for tracking."""
    if key < 0:
        return None
    arrows = {
        65361: "b",
        65362: "u",
        65363: "n",
        65364: "l",
        0xFF51: "b",
        0xFF52: "u",
        0xFF53: "n",
        0xFF54: "l",
    }
    if key in arrows:
        return arrows[key]
    ch = key & 0xFF
    if ch == ord("w"):
        return "u"
    if ch == ord("s"):
        return "l"
    if ch == ord("a"):
        return "b"
    if ch == ord("d"):
        return "n"
    return None


def tracking_command(dx: int, dy: int, deadzone: int, direction_mode: str) -> Optional[str]:
    x_dir = -1 if dx < -deadzone else (1 if dx > deadzone else 0)
    y_dir = -1 if dy < -deadzone else (1 if dy > deadzone else 0)

    if x_dir == 0 and y_dir == 0:
        return None

    if direction_mode == "axis":
        # If both axes are off-center, correct the larger pixel error first so
        # vertical (shoulder+elbow via u/l) is not starved by always preferring b/n.
        if x_dir != 0 and y_dir != 0:
            if abs(dx) >= abs(dy):
                return "b" if x_dir < 0 else "n"
            return "u" if y_dir < 0 else "l"
        if x_dir < 0:
            return "b"
        if x_dir > 0:
            return "n"
        if y_dir < 0:
            return "u"
        return "l"

    keypad_map = {
        (0, -1): "8",
        (1, -1): "9",
        (1, 0): "6",
        (1, 1): "3",
        (0, 1): "2",
        (-1, 1): "1",
        (-1, 0): "4",
        (-1, -1): "7",
    }
    return keypad_map[(x_dir, y_dir)]


def opposite_command(cmd: str, direction_mode: str) -> Optional[str]:
    if direction_mode == "axis":
        return {"b": "n", "n": "b", "u": "l", "l": "u"}.get(cmd)
    return {
        "8": "2",
        "2": "8",
        "4": "6",
        "6": "4",
        "7": "3",
        "3": "7",
        "9": "1",
        "1": "9",
    }.get(cmd)


class SpeechEngine:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.engine = None
        if not enabled:
            return
        try:
            import pyttsx3

            self.engine = pyttsx3.init()
        except Exception as exc:  # pragma: no cover - depends on local audio stack
            print(f"Voice disabled: could not initialize pyttsx3 ({exc})")
            self.enabled = False

    def speak(self, text: str) -> None:
        if not self.enabled or self.engine is None:
            return
        try:
            self.engine.say(text)
            self.engine.runAndWait()
        except Exception as exc:  # pragma: no cover - depends on local audio stack
            print(f"Voice disabled after runtime error: {exc}")
            self.enabled = False
            self.engine = None


def read_terminal_line_nonblocking() -> Optional[str]:
    if sys.stdin is None:
        return None
    try:
        readable, _, _ = select.select([sys.stdin], [], [], 0)
    except (OSError, ValueError):
        return None
    if not readable:
        return None
    line = sys.stdin.readline()
    if not line:
        return None
    return line.strip()


def detect_marker_center(
    frame,
    lower: Tuple[int, int, int],
    upper: Tuple[int, int, int],
    kernel,
    min_area: int,
) -> Tuple[Optional[int], Optional[int], float, Optional[Tuple[int, int, int, int]]]:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, lower, upper)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, None, 0.0, None
    c = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(c)
    if area < min_area:
        return None, None, area, None
    x, y, ww, hh = cv2.boundingRect(c)
    return x + ww // 2, y + hh // 2, area, (x, y, ww, hh)


def run_plane_locked_j(ser: serial.Serial, attempts: int, pause_s: float) -> None:
    """Tell MCU to trace J relative to pose saved with s (firmware y)."""
    n = max(1, int(attempts))
    pause_s = max(0.0, float(pause_s))
    for i in range(n):
        print(f"Plane-locked J: run {i + 1}/{n} (serial y)...")
        drain_serial_messages(ser)
        send_cmd(ser, "y")
        deadline = time.monotonic() + 120.0
        done = False
        while time.monotonic() < deadline:
            for line in drain_serial_messages(ser):
                low = line.lower()
                if "done j" in low or "no drawing pose" in low:
                    done = True
                    break
            if done:
                break
            time.sleep(0.08)
        if not done:
            print("Note: no completion line from MCU within 120s (motion may still be running).")
        if i + 1 < n:
            print(f"Pausing {pause_s:.1f}s before next run.")
            time.sleep(pause_s)



def main() -> int:
    args = parse_args()
    if _serial_port_looks_placeholder(args.port):
        print(
            f"ERROR: --port looks like a placeholder ({args.port!r}). "
            "Use the real USB device path from: ls /dev/cu.usbmodem*"
        )
        return 1
    if args.learn_attempts is not None or args.learn_target_score is not None:
        print(
            "Note: --learn-attempts / --learn-target-score are ignored (camera learning was removed). "
            "Save pose with s, then draw with y or --plane-j-attempts."
        )
    global TRACE_SERIAL, TRACE_FUNCTIONS
    TRACE_SERIAL = args.trace_serial
    TRACE_FUNCTIONS = args.trace_functions
    speaker = SpeechEngine(enabled=args.voice)
    _trace_fn("main() startup")

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"Could not open camera index {args.camera}")
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.0)
    except serial.SerialException as exc:
        print(f"Could not open serial port {args.port}: {exc}")
        cap.release()
        return 1
    # Give the board time to reset and validate command channel.
    handshake_ok = wait_for_mcu_handshake(
        ser=ser,
        warmup_ms=args.serial_warmup_ms,
        timeout_ms=args.serial_handshake_timeout_ms,
        retries=args.serial_handshake_retries,
    )
    if not handshake_ok and args.auto_port_scan:
        candidate_port = find_responsive_serial_port(
            baud=args.baud,
            warmup_ms=args.serial_warmup_ms,
            timeout_ms=args.serial_handshake_timeout_ms,
        )
        if candidate_port and candidate_port != args.port:
            print(f"Switching serial port from {args.port} to {candidate_port}")
            try:
                ser.close()
            except Exception:
                pass
            try:
                ser = serial.Serial(candidate_port, args.baud, timeout=0.0)
                args.port = candidate_port
                handshake_ok = wait_for_mcu_handshake(
                    ser=ser,
                    warmup_ms=args.serial_warmup_ms,
                    timeout_ms=args.serial_handshake_timeout_ms,
                    retries=args.serial_handshake_retries,
                )
            except serial.SerialException as exc:
                print(f"Could not switch to scanned port {candidate_port}: {exc}")
    if not handshake_ok and args.require_handshake:
        print(
            "ERROR: No responsive robotic-arm MCU found. "
            "Connect the arm USB serial controller, then rerun."
        )
        cap.release()
        try:
            ser.close()
        except Exception:
            pass
        cv2.destroyAllWindows()
        return 2
    startup_msgs = drain_serial_messages(ser)
    caps = detect_mcu_capabilities(startup_msgs)
    runtime_direction_mode = args.direction_mode
    if runtime_direction_mode == "8way" and not caps.supports_8way:
        runtime_direction_mode = "axis"
        print("MCU does not report 8-way stylus support; falling back to axis movement (b/n/u/l).")
    if args.stylus_start and not caps.supports_stylus_mode:
        print("MCU does not report stylus mode support; skipping stylus-start sequence (p,z).")

    print("Tracking started.")
    print(
        "Keys: arrows or WASD=jog shoulder/base, e/t=elbow out/in, "
        "q=quit, h=home, o/c=gripper, p/k=stylus/claw, x/z=stylus touch save/go, "
        "s=save drawing plane pose, g=go to saved plane, y=plane-locked J (after s), "
        "= log joint degrees to serial, i=capture marker coords to terminal"
    )
    if runtime_direction_mode == "8way":
        print("Direction mode: 8way (sends 8/9/6/3/2/1/4/7 for N/NE/E/SE/S/SW/W/NW).")
    else:
        print("Direction mode: axis (sends b/n/u/l).")
    print("Plane-locked J: jog until tip touches paper, press s, then y or bot: draw letter j with a single line.")
    print("Move a colored stylus marker (default green) in front of camera.")
    if args.bot_chat:
        print(
            "Bot chat: save plane with s first, then e.g. 'draw the letter j with a single line' "
            f"(runs y up to {args.plane_j_attempts} time(s))."
        )
    if args.voice:
        if speaker.enabled:
            print("Voice replies enabled.")
        else:
            print("Voice replies requested, but unavailable on this machine.")

    lower = (args.h_min, args.s_min, args.v_min)
    upper = (args.h_max, args.s_max, args.v_max)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    last_cmd_ts = 0.0
    min_interval = max(0.05, args.interval_ms / 1000.0)
    reverse_guard = max(0.0, args.reverse_guard_ms / 1000.0)
    stable_frames = max(1, args.stable_frames)
    pending_cmd: Optional[str] = None
    pending_count = 0
    last_sent_cmd: Optional[str] = None
    if args.stylus_start and caps.supports_stylus_mode:
        send_cmd(ser, "p")
        time.sleep(0.12)
        send_cmd(ser, "z")
        time.sleep(0.12)

    while True:
        drain_serial_messages(ser)
        ok, frame = cap.read()
        if not ok:
            print("Camera frame read failed.")
            break

        frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        cx, cy = w // 2, h // 2

        target_x, target_y, largest_area, rect = detect_marker_center(frame, lower, upper, kernel, args.min_area)
        if rect is not None and target_x is not None and target_y is not None:
            x, y, ww, hh = rect
            cv2.rectangle(frame, (x, y), (x + ww, y + hh), (0, 255, 0), 2)
            cv2.circle(frame, (target_x, target_y), 6, (0, 255, 0), -1)

        cv2.line(frame, (cx - args.deadzone, 0), (cx - args.deadzone, h), (255, 255, 0), 1)
        cv2.line(frame, (cx + args.deadzone, 0), (cx + args.deadzone, h), (255, 255, 0), 1)
        cv2.line(frame, (0, cy - args.deadzone), (w, cy - args.deadzone), (255, 255, 0), 1)
        cv2.line(frame, (0, cy + args.deadzone), (w, cy + args.deadzone), (255, 255, 0), 1)
        cv2.drawMarker(frame, (cx, cy), (0, 0, 255), cv2.MARKER_CROSS, 16, 2)

        status = "No target"
        good_view = False
        now = time.monotonic()
        if target_x is not None and target_y is not None:
            dx = target_x - cx
            dy = target_y - cy
            status = f"Target dx={dx} dy={dy} area={int(largest_area)}"
            good_view = True

            candidate = tracking_command(dx, dy, args.deadzone, runtime_direction_mode)
            if candidate is None:
                pending_cmd = None
                pending_count = 0
                status += " hold"
            else:
                if candidate == pending_cmd:
                    pending_count += 1
                else:
                    pending_cmd = candidate
                    pending_count = 1
                status += f" cmd={candidate} stable={pending_count}/{stable_frames}"

                if pending_count >= stable_frames and now - last_cmd_ts >= min_interval:
                    opp = opposite_command(last_sent_cmd, runtime_direction_mode)
                    if (
                        last_sent_cmd is not None
                        and opp is not None
                        and candidate == opp
                        and now - last_cmd_ts < reverse_guard
                    ):
                        status += " reverse-guard"
                    else:
                        send_cmd(ser, candidate)
                        last_cmd_ts = now
                        last_sent_cmd = candidate

        cv2.putText(
            frame,
            status,
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
        cv2.imshow("Adeept Camera Tracking", frame)

        if hasattr(cv2, "waitKeyEx"):
            key = cv2.waitKeyEx(1)
        else:
            key = cv2.waitKey(1) & 0xFF

        jog = manual_move_command(key)
        if jog is not None:
            send_cmd(ser, jog)
            last_cmd_ts = now
        elif (key & 0xFF) in (ord("8"), ord("9"), ord("6"), ord("3"), ord("2"), ord("1"), ord("4"), ord("7")):
            send_cmd(ser, chr(key & 0xFF))
            last_cmd_ts = now
        elif (key & 0xFF) == ord("q"):
            break
        elif (key & 0xFF) == ord("h"):
            send_cmd(ser, "h")
        elif (key & 0xFF) == ord("o"):
            send_cmd(ser, "o")
        elif (key & 0xFF) == ord("c"):
            send_cmd(ser, "c")
        elif (key & 0xFF) in (ord("p"), ord("P")):
            send_cmd(ser, "p")
        elif (key & 0xFF) in (ord("k"), ord("K")):
            send_cmd(ser, "k")
        elif (key & 0xFF) in (ord("x"), ord("X")):
            send_cmd(ser, "x")
        elif (key & 0xFF) in (ord("z"), ord("Z")):
            send_cmd(ser, "z")
        elif (key & 0xFF) in (ord("e"), ord("E")):
            send_cmd(ser, "e")
            last_cmd_ts = now
        elif (key & 0xFF) in (ord("t"), ord("T")):
            send_cmd(ser, "t")
            last_cmd_ts = now
        elif (key & 0xFF) in (ord("s"), ord("S")):
            send_cmd(ser, "s")
        elif (key & 0xFF) in (ord("g"), ord("G")):
            send_cmd(ser, "g")
        elif (key & 0xFF) in (ord("y"), ord("Y")):
            run_plane_locked_j(ser, args.plane_j_attempts, args.plane_j_pause_s)
        elif (key & 0xFF) == ord("="):
            send_cmd(ser, "=")
        elif (key & 0xFF) in (ord("i"), ord("I")):
            if target_x is not None and target_y is not None:
                nx = target_x / max(1.0, float(w))
                ny = target_y / max(1.0, float(h))
                tdx = target_x - cx
                tdy = target_y - cy
                print(
                    f"CAPTURE marker: pixel=({target_x}, {target_y}) "
                    f"norm_xy=({nx:.6f}, {ny:.6f}) "
                    f"delta_from_center_px=({tdx}, {tdy}) "
                    f"frame_wh=({w}, {h}) contour_area={int(largest_area)}"
                )
                if rect is not None:
                    rx, ry, rw, rh = rect
                    print(f"CAPTURE bbox_xywh=({rx}, {ry}, {rw}, {rh})")
            else:
                print("CAPTURE: no marker detected — check lighting, color, or --h-min/--h-max tuning.")

        if args.bot_chat:
            command_text = read_terminal_line_nonblocking()
            if command_text:
                if command_text.lower() in {"quit", "exit"}:
                    print("Bot: Ending session.")
                    break
                # In bot-chat mode, allow direct one-key firmware commands from terminal input.
                direct_serial_cmd = command_text.strip().lower()
                if len(direct_serial_cmd) == 1 and direct_serial_cmd in {
                    "h",
                    "b",
                    "n",
                    "u",
                    "l",
                    "e",
                    "t",
                    "p",
                    "k",
                    "x",
                    "z",
                    "o",
                    "c",
                    "8",
                    "9",
                    "6",
                    "3",
                    "2",
                    "1",
                    "4",
                    "7",
                    "j",
                    "d",
                    "s",
                    "g",
                    "f",
                    "v",
                    "y",
                    "=",
                }:
                    send_cmd(ser, direct_serial_cmd)
                    print(f"Bot action: sent direct serial '{direct_serial_cmd}'")
                    last_cmd_ts = now
                    continue
                decision = evaluate_command(command_text, CapabilityContext())
                print(f"Bot: {decision.response}")
                speaker.speak(decision.response)
                _trace_fn(
                    "bot_decision("
                    f"should_execute={decision.should_execute}, action={decision.action}, letter={decision.letter})"
                )
                if decision.should_execute and decision.action == "plane_j" and decision.letter:
                    if not handshake_ok:
                        print("Bot: Serial handshake is not healthy; command execution may fail.")
                    run_plane_locked_j(ser, args.plane_j_attempts, args.plane_j_pause_s)
                    print(f"Bot: Finished plane-locked J run(s) for {decision.letter.upper()}.")
                    last_cmd_ts = time.monotonic()
                elif decision.should_execute and decision.serial_command:
                    send_cmd(ser, decision.serial_command)
                    print(f"Bot action: sent '{decision.serial_command}'")
                    last_cmd_ts = now

    cap.release()
    ser.close()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
