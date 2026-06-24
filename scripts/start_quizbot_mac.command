#!/bin/bash
set -u

PORT=8000
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$APP_DIR" || exit 1

echo "========================================"
echo " QuizBot Studio launcher for macOS"
echo " Folder: $APP_DIR"
echo " Port:   $PORT"
echo "========================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is not installed."
  echo "Install Python 3 from https://www.python.org/downloads/macos/ and run this file again."
  echo
  read -r -p "Press Enter to close..."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Creating Python virtual environment..."
  python3 -m venv .venv || exit 1
fi

source ".venv/bin/activate" || exit 1

echo "Installing/updating Python dependencies..."
python -m pip install --upgrade pip
pip install -r backend/requirements.txt || exit 1
echo

if [ ! -f "backend/.env" ]; then
  echo "backend/.env was not found. Creating it from backend/.env.example..."
  cp backend/.env.example backend/.env
  echo
  echo "Telegram profiles are configured in the web platform: Accounts."
  echo "backend/.env is only for optional service integrations."
fi

# Build the web UI if it is missing — backend serves frontend/dist, which is
# not stored in git, so a fresh clone has no UI until it is built.
if [ ! -d "frontend/dist" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "ERROR: the web UI is not built yet and npm (Node.js) is not installed."
    echo "Install Node.js 20 LTS from https://nodejs.org/ and run this file again."
    echo
    read -r -p "Press Enter to close..."
    exit 1
  fi
  echo "Building the web UI (first run, this can take a minute)..."
  ( cd frontend && npm install && npm run build ) || exit 1
  echo
fi

PIDS="$(lsof -tiTCP:${PORT} -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "$PIDS" ]; then
  echo "Port $PORT is busy. Stopping process(es): $PIDS"
  kill $PIDS 2>/dev/null || true
  sleep 2

  REMAINING="$(lsof -tiTCP:${PORT} -sTCP:LISTEN 2>/dev/null || true)"
  if [ -n "$REMAINING" ]; then
    echo "Port $PORT is still busy. Force stopping process(es): $REMAINING"
    kill -9 $REMAINING 2>/dev/null || true
    sleep 1
  fi
fi

echo "Starting QuizBot Studio..."
echo "Open: http://127.0.0.1:${PORT}"
echo

(sleep 2 && open "http://127.0.0.1:${PORT}") >/dev/null 2>&1 &

python -m backend.studio_api

echo
echo "QuizBot Studio stopped."
read -r -p "Press Enter to close..."
