#!/usr/bin/env bash
# Build and optionally upload the Adeept 5 DOF Arm sketch.
# Usage: ./build.sh [upload]
# Upload: pass "upload" to flash the board (board must be connected).

set -e
SKETCH_DIR="$(cd "$(dirname "$0")" && pwd)"
FQBN="arduino:avr:uno"

# Use same libraries as Arduino IDE (needed for Servo etc. when using arduino-cli)
export ARDUINO_DIRECTORIES_USER="${ARDUINO_DIRECTORIES_USER:-$HOME/Library/Arduino15}"

cd "$SKETCH_DIR"
BUILD_PATH="$SKETCH_DIR/build"
echo "Compiling $SKETCH_DIR for $FQBN ..."
arduino-cli compile --fqbn "$FQBN" --build-path "$BUILD_PATH" .

if [[ "${1:-}" == "upload" ]]; then
  PORT="${2:-}"
  if [[ -z "$PORT" ]]; then
    # Adeept/clones often use CH340 → show up as usbserial; try that first, then usbmodem
    PORT=$(arduino-cli board list | awk '/usbserial/{print $1; exit}')
    [[ -z "$PORT" ]] && PORT=$(arduino-cli board list | awk '/usbmodem/{print $1; exit}')
  fi
  if [[ -z "$PORT" ]]; then
    echo "No serial port found. Connect the board and run: arduino-cli board list"
    echo "Then: ./build.sh upload /dev/cu.usbserial-XXXX   or   ./build.sh upload /dev/cu.usbmodemXXXX"
    exit 1
  fi
  echo "Uploading to $PORT ..."
  echo "Tip: If upload fails with 'not in sync', try the other port or press RESET on the board when you see 'Uploading'."
  if arduino-cli upload -p "$PORT" --fqbn "$FQBN" --build-path "$BUILD_PATH" . --discovery-timeout 10s; then
    echo "Done. Open Serial Monitor at 9600 baud to send commands: h d o c"
  else
    echo ""
    echo "Upload failed. Try:"
    echo "  1. ./build.sh upload /dev/cu.usbserial-2130"
    echo "  2. ./build.sh upload /dev/cu.usbmodem010NTLEGE0322"
    echo "  3. Press RESET on the board right when you run upload."
    echo "  4. Close Serial Monitor or any app using the port, then upload again."
    exit 1
  fi
fi
