#!/usr/bin/env bash
# Open serial monitor to control the Adeept arm (9600 baud).
# Commands: h = home, d = demo, o = open gripper, c = close gripper
# Press Ctrl+C to exit.

PORT="${1:-/dev/cu.usbserial-2130}"
echo "Opening monitor on $PORT at 9600 baud. Type h d o c to control the arm. Ctrl+C to exit."
exec arduino-cli monitor -p "$PORT" -c baudrate=9600
