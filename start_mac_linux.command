#!/bin/bash
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null; then
  echo "Python 3 wurde nicht gefunden. Bitte von https://www.python.org/downloads/ installieren."
  read -r -p "Eingabetaste zum Beenden ..."; exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "Erster Start: Umgebung wird eingerichtet, bitte warten ..."
  python3 -m venv .venv && .venv/bin/python -m pip install --upgrade pip \
    && .venv/bin/python -m pip install -r requirements.txt || { read -r -p "Fehler – Eingabetaste ..."; exit 1; }
fi
exec .venv/bin/python AeroTagger.pyw
