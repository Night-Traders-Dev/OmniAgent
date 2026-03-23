#!/bin/bash
# Start BitNet b1.58 2B server on port 8081
# Runs alongside Ollama (port 11434) for parallel inference

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODEL="$SCRIPT_DIR/model/ggml-model-i2_s.gguf"
PORT="${BITNET_PORT:-8081}"
THREADS="${BITNET_THREADS:-4}"
CTX="${BITNET_CTX:-2048}"

echo "Starting BitNet b1.58-2B server on port $PORT ($THREADS threads, ctx=$CTX)"
exec "$SCRIPT_DIR/llama-server" \
    -m "$MODEL" \
    --host 0.0.0.0 \
    --port "$PORT" \
    -t "$THREADS" \
    -c "$CTX" \
    -n 4096 \
    --temp 0.7 \
    -cb
