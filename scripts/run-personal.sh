#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
config="${AXONHUB_PERSONAL_CONNECTION_FILE:-data/personal/connection.json}"
worker_port="${AXONHUB_PERSONAL_WORKER_PORT:-8093}"
binary="${AXONHUB_PERSONAL_BINARY:-dist/axonhub-personal}"
if [[ ! -f "$config" || ! -x "$binary" ]]; then
  echo "请先准备私有连接配置并构建 Go 程序，见 docs/personal-edition.md" >&2
  exit 1
fi
# Do not start a second worker over an occupied port.
python3 - "$worker_port" <<'PY'
import socket,sys
s=socket.socket()
try:s.bind(("127.0.0.1",int(sys.argv[1])))
except OSError:raise SystemExit("Python worker 端口已占用，请先检查运行中的实例")
finally:s.close()
PY
mkdir -p data/personal
chmod 700 data/personal
PYTHONPATH="$project_dir/personal" python3 -m axonhub_personal --config "$config" --port "$worker_port" &
worker_pid=$!
cleanup() { kill "$worker_pid" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
for ((i=0;i<50;i++)); do
  kill -0 "$worker_pid" 2>/dev/null || exit 1
  [[ -s data/personal/worker.token ]] && break
  sleep .1
done
export AXONHUB_PERSONAL_MODE=true
export AXONHUB_PERSONAL_WORKER_URL="http://127.0.0.1:$worker_port"
export AXONHUB_PERSONAL_TOKEN_FILE="$project_dir/data/personal/worker.token"
export AXONHUB_PERSONAL_POLICY_FILE="$project_dir/data/personal/policy.json"
export AXONHUB_SERVER_HOST="${AXONHUB_SERVER_HOST:-127.0.0.1}"
export AXONHUB_SERVER_PORT="${AXONHUB_SERVER_PORT:-8091}"
export AXONHUB_SERVER_PID_FILE="$project_dir/data/personal/axonhub.pid"
export AXONHUB_DB_DIALECT=sqlite3
export AXONHUB_DB_DSN="${AXONHUB_DB_DSN:-file:$project_dir/data/personal/axonhub.db?cache=shared&_fk=1&_pragma=journal_mode(WAL)}"
"$binary"
