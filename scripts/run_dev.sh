#!/usr/bin/env bash
set -e

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Fichier .env créé à partir de .env.example (mode test, sans Firebase)."
fi

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
