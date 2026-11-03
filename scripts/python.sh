#!/bin/sh
# Runs Python with the API's packages: with uv when it is installed (nothing to set up), else from .venv.
#   sh scripts/python.sh -m uvicorn app:app --port 8000
# kokoro-onnx needs Python 3.10–3.13, so uv is asked for 3.12.
set -e
cd "$(dirname "$0")/.."
if command -v uv >/dev/null 2>&1; then
  exec uv run --quiet --no-project --python 3.12 --with-requirements requirements-dev.txt -- python "$@"
fi
if [ -x .venv/bin/python ]; then
  exec .venv/bin/python "$@"
fi
echo "No Python environment: install uv (https://docs.astral.sh/uv/), or run" >&2
echo "  python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt" >&2
exit 1
