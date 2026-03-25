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


def tracking_command(dx: int, dy: int, deadzone: int, direction_mode: str) -> Optional[str]:
    x_dir = -1 if dx < -deadzone else (1 if dx > deadzone else 0)
    y_dir = -1 if dy < -deadzone else (1 if dy > deadzone else 0)

    if x_dir == 0 and y_dir == 0:
        return None

    if direction_mode == "axis":
        if x_dir < 0:
            return "b"
        if x_dir > 0:
            return "n"
        if y_dir < 0:
            return "u"
        return "l"

    # 8-way stylus map (numeric keypad direction commands).
    keypad_map = {
        (0, -1): "8",    # north
        (1, -1): "9",    # north-east
        (1, 0): "6",     # east
        (1, 1): "3",     # south-east
        (0, 1): "2",     # south
        (-1, 1): "1",    # south-west
        (-1, 0): "4",    # west
        (-1, -1): "7",   # north-west
    }
    return keypad_map[(x_dir, y_dir)]


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
        "Keys: arrows or WASD=jog shoulder/base, e/t=elbow out/in, "
        "q=quit, h=home, o/c=gripper, p/k=stylus/claw mode, x=save stylus touch home, z=go touch home"
    )
    if args.direction_mode == "8way":
        print("Direction mode: 8way (sends 8/9/6/3/2/1/4/7 for N/NE/E/SE/S/SW/W/NW).")
    else:
        print("Direction mode: axis (sends b/n/u/l).")
    print("Move a colored stylus marker (default green) in front of camera.")

    lower = (args.h_min, args.s_min, args.v_min)
    upper = (args.h_max, args.s_max, args.v_max)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    last_cmd_ts = 0.0
    min_interval = max(0.05, args.interval_ms / 1000.0)
    if args.stylus_start:
        send_cmd(ser, "p")
        time.sleep(0.12)
        send_cmd(ser, "z")
        time.sleep(0.12)

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

            if now - last_cmd_ts >= min_interval:
                # Camera feed is mirrored; firmware command map keeps object centered.
                cmd = tracking_command(dx, dy, args.deadzone, args.direction_mode)
                if cmd is not None:
                    send_cmd(ser, cmd)
                    last_cmd_ts = now

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

    cap.release()
    ser.close()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
