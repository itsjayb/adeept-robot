#!/usr/bin/env python3
"""
Simple camera viewer for Adeept arm vision setup.

Usage examples:
  python3 camera_view.py
  python3 camera_view.py --camera 1 --width 1280 --height 720
"""

import argparse
from datetime import datetime
from pathlib import Path

import cv2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show a live camera feed.")
    parser.add_argument(
        "--camera",
        type=int,
        default=0,
        help="Camera device index (default: 0)",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=640,
        help="Requested frame width (default: 640)",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=480,
        help="Requested frame height (default: 480)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=30,
        help="Requested FPS (default: 30)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"Could not open camera index {args.camera}.")
        print("Try a different index: --camera 1 (or 2, 3...)")
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, args.fps)

    print("Camera viewer started.")
    print("Press 'q' to quit, 's' to save a snapshot.")

    snapshots_dir = Path("snapshots")
    snapshots_dir.mkdir(exist_ok=True)

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Failed to read frame from camera.")
            break

        h, w = frame.shape[:2]
        text = f"{w}x{h}"
        cv2.putText(
            frame,
            text,
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
        cv2.imshow("Adeept Camera View", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("s"):
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_path = snapshots_dir / f"snapshot_{stamp}.jpg"
            cv2.imwrite(str(image_path), frame)
            print(f"Saved {image_path}")

    cap.release()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
