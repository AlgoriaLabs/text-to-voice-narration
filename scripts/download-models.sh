#!/bin/sh
# Downloads the Kokoro-82M model (Apache 2.0) and its voices from the kokoro-onnx releases on GitHub, and checks them
# against pinned SHA-256 hashes. The Dockerfile runs it at build time; run it once for npm run dev.
#
#   sh scripts/download-models.sh [folder] [model]
#
# folder: default ./models. model: kokoro-v1.0.onnx (default, 310 MB, full precision) or kokoro-v1.0.int8.onnx
# (88 MB, quantized: smaller, about as fast on CPU, slightly lower quality). Set KOKORO_MODEL to the same name.
set -eu

DIR=${1:-models}
MODEL=${2:-${KOKORO_MODEL:-kokoro-v1.0.onnx}}
BASE=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0

expected() {
  case "$1" in
    kokoro-v1.0.onnx) echo 7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5 ;;
    kokoro-v1.0.int8.onnx) echo 6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb ;;
    voices-v1.0.bin) echo bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d ;;
    *) echo "unknown model file: $1" >&2; exit 1 ;;
  esac
}

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1
  else python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"
  fi
}

fetch() {
  if command -v curl >/dev/null 2>&1; then curl -fsSL --retry 3 -o "$2" "$1"
  else python3 -c 'import sys,urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$1" "$2"
  fi
}

mkdir -p "$DIR"
for file in "$MODEL" voices-v1.0.bin; do
  want=$(expected "$file")
  if [ -f "$DIR/$file" ] && [ "$(sha256 "$DIR/$file")" = "$want" ]; then
    echo "✓ $DIR/$file is already here"
    continue
  fi
  echo "… downloading $file"
  fetch "$BASE/$file" "$DIR/$file.part"
  got=$(sha256 "$DIR/$file.part")
  if [ "$got" != "$want" ]; then
    rm -f "$DIR/$file.part"
    echo "✗ $file: SHA-256 is $got, expected $want" >&2
    exit 1
  fi
  mv "$DIR/$file.part" "$DIR/$file"
  echo "✓ $DIR/$file"
done
