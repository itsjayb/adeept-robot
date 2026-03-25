#!/usr/bin/env python3
"""
Track a colored target and steer the Adeept arm over serial.

Default target color is green in HSV space. Tune with CLI flags if needed.
"""

import argparse
import time
from typing import Optional

import cv2
import serial


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Camera tracking -> arm serial control")
    parser.add_argument("--camera", type=int, default=0, help="Camera index (default: 0)")
    parser.add_argument("--port", required=True, help="Serial port, e.g. /dev/cu.usbserial-2130")
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
    return parser.parse_args()


def send_cmd(ser: serial.Serial, cmd: str) -> None:
    ser.write(cmd.encode("ascii"))


def manual_move_command(key: int) -> Optional[str]:
    """Map keyboard to the same single-char jog commands the firmware uses for tracking."""
    if key < 0:
        return None
    # Qt/GTK arrow keys from cv2.waitKeyEx (also accept X11-style masks).
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


def tracking_move_command(dx: int, dy: int, deadzone: int) -> Optional[str]:
    """
    Pick one tracking command based on the dominant axis offset.
    This reduces jitter from frame-to-frame axis switching.
    """
    x_cmd: Optional[str] = None
    y_cmd: Optional[str] = None
    if dx < -deadzone:
        x_cmd = "b"
    elif dx > deadzone:
        x_cmd = "n"

    if dy < -deadzone:
        y_cmd = "u"
    elif dy > deadzone:
        y_cmd = "l"

    if x_cmd is None and y_cmd is None:
        return None
    if x_cmd is None:
        return y_cmd
    if y_cmd is None:
        return x_cmd
    if abs(dx) >= abs(dy):
        return x_cmd
    return y_cmd


def main() -> int:
    args = parse_args()

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"Could not open camera index {args.camera}")
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.1)
    except serial.SerialException as exc:
        print(f"Could not open serial port {args.port}: {exc}")
        cap.release()
        return 1

    print("Tracking started.")
    print(
        "Keys: arrows or WASD=jog shoulder/base (up/down/left/right), "
        "e/t=elbow out/in, q=quit, h=home, o/c=gripper open/close"
    )
    print("Move a green object in front of camera.")

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
    opposite_cmd = {"b": "n", "n": "b", "u": "l", "l": "u"}

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Camera frame read failed.")
            break

        frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        cx, cy = w // 2, h // 2

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, lower, upper)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        target_x = None
        target_y = None
        largest_area = 0.0
        if contours:
            c = max(contours, key=cv2.contourArea)
            largest_area = cv2.contourArea(c)
            if largest_area >= args.min_area:
                x, y, ww, hh = cv2.boundingRect(c)
                target_x = x + ww // 2
                target_y = y + hh // 2
                cv2.rectangle(frame, (x, y), (x + ww, y + hh), (0, 255, 0), 2)
                cv2.circle(frame, (target_x, target_y), 6, (0, 255, 0), -1)

        cv2.line(frame, (cx - args.deadzone, 0), (cx - args.deadzone, h), (255, 255, 0), 1)
        cv2.line(frame, (cx + args.deadzone, 0), (cx + args.deadzone, h), (255, 255, 0), 1)
        cv2.line(frame, (0, cy - args.deadzone), (w, cy - args.deadzone), (255, 255, 0), 1)
        cv2.line(frame, (0, cy + args.deadzone), (w, cy + args.deadzone), (255, 255, 0), 1)
        cv2.drawMarker(frame, (cx, cy), (0, 0, 255), cv2.MARKER_CROSS, 16, 2)

        status = "No target"
        now = time.monotonic()
        if target_x is not None and target_y is not None:
            dx = target_x - cx
            dy = target_y - cy
            status = f"Target dx={dx} dy={dy} area={int(largest_area)}"
            candidate = tracking_move_command(dx, dy, args.deadzone)
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

                # Only emit movement when input is stable enough and rate limits allow it.
                if pending_count >= stable_frames and now - last_cmd_ts >= min_interval:
                    if (
                        last_sent_cmd is not None
                        and candidate == opposite_cmd[last_sent_cmd]
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
        elif (key & 0xFF) == ord("q"):
            break
        elif (key & 0xFF) == ord("h"):
            send_cmd(ser, "h")
        elif (key & 0xFF) == ord("o"):
            send_cmd(ser, "o")
        elif (key & 0xFF) == ord("c"):
            send_cmd(ser, "c")
        elif (key & 0xFF) in (ord("e"), ord("E")):
            send_cmd(ser, "e")
            last_cmd_ts = now
        elif (key & 0xFF) in (ord("t"), ord("T")):
            send_cmd(ser, "t")
            last_cmd_ts = now

    cap.release()
    ser.close()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
