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
  echo "Fill backend/.env with Telegram/OpenAI values, then return to this window."
  open -e backend/.env
  echo
  read -r -p "Press Enter after backend/.env is filled..."
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
