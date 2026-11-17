#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -f config.json ]; then
  cp config.example.json config.json
  echo "Создан config.json — отредактируй настройки telegram/email."
fi

if [ ! -d venv ]; then
  python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt

exec uvicorn main:app --host 0.0.0.0 --port 8080
