#!/usr/bin/env bash
# Install and start local TrialGPT on Linux / WSL / macOS (NVIDIA GPU or Apple silicon).
#
#   bash install.sh                       # model chosen from GPU memory
#   MODEL=gemma4:12b bash install.sh
#
# Installs what is missing (Ollama, uv), pulls the model, clones the code, creates a Python 3.12 environment and
# starts the interface on http://127.0.0.1:8090. Run it again any time: finished steps are skipped, code is updated.
set -euo pipefail

DIR="${DIR:-$HOME/TrialGPT}"
BRANCH="${BRANCH:-claude/trialgpt-local-lcvm9p}"
NUM_CTX="${NUM_CTX:-16384}"
TIMEOUT="${TIMEOUT:-3600}"   # seconds per LLM call: big models partly on the CPU are slow
MODEL="${MODEL:-}"

command -v git >/dev/null || { echo "git is required (apt install git / xcode-select --install)"; exit 1; }
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
command -v uv >/dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$HOME/.local/bin:$PATH"; }

# 1. Model: largest Gemma 4 that leaves room for a 16k context on this GPU
if [ -z "$MODEL" ]; then
  mib=0
  if command -v nvidia-smi >/dev/null; then
    mib=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1 | tr -d ' ')
  elif [ "$(uname)" = Darwin ]; then
    mib=$(( $(sysctl -n hw.memsize) / 1048576 * 2 / 3 ))   # unified memory usable by the GPU
  fi
  mib=${mib:-0}
  if [ "$mib" -ge 16000 ]; then MODEL=gemma4:12b; elif [ "$mib" -ge 6000 ]; then MODEL=gemma4:e4b; else MODEL=gemma4:e2b; fi
  echo "GPU memory: ${mib} MiB -> $MODEL (override with MODEL=...)"
fi

# 2. Ollama server
up() { curl -s -m 2 http://127.0.0.1:11434/api/version >/dev/null; }
if ! up; then
  (nohup ollama serve >/tmp/ollama.log 2>&1 &)
  for _ in $(seq 30); do up && break; sleep 1; done
  up || { echo "Ollama did not start (see /tmp/ollama.log)"; exit 1; }
fi
ollama pull "$MODEL"

# 3. Code
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch origin "$BRANCH" && git -C "$DIR" checkout "$BRANCH" && git -C "$DIR" pull --ff-only origin "$BRANCH"
else
  git clone --branch "$BRANCH" --depth 1 https://github.com/zandis/Auto-GPT.git "$DIR"
fi
cd "$DIR/trialgpt"

# 4. Python environment (CPU torch is enough: only the small MedCPT retrievers use it)
PY="$PWD/.venv/bin/python"
[ -x "$PY" ] || uv venv -p 3.12 .venv
if [ "$(uname)" = Linux ]; then
  uv pip install --python "$PY" --index-url https://download.pytorch.org/whl/cpu torch
fi
uv pip install --python "$PY" -e .
"$PY" -c "import nltk; nltk.download('punkt_tab', quiet=True); nltk.download('punkt', quiet=True)"

# 5. Launcher
cat > start-trialgpt.sh <<EOF
#!/usr/bin/env bash
export TG_LLM_MODEL="$MODEL" TG_LLM_NUM_CTX="$NUM_CTX" TG_LLM_THINK=false TG_LLM_TIMEOUT="$TIMEOUT"
cd "$PWD"
( sleep 6; (xdg-open http://127.0.0.1:8090 || open http://127.0.0.1:8090 || true) >/dev/null 2>&1 ) &
exec "$PY" -m trialgpt_local.app
EOF
chmod +x start-trialgpt.sh
echo "Installed. Start it any time with: $PWD/start-trialgpt.sh"
[ "${NO_START:-}" = 1 ] || exec ./start-trialgpt.sh
