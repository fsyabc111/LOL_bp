#!/usr/bin/env bash
# Start the local app in the background: ./start.sh   (PORT=8001 ./start.sh to change the port)
# Rebuilds web/dist when the frontend source is newer; PID and log live in data/app/ (gitignored).
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"
PID_FILE=data/app/server.pid
LOG_FILE=data/app/server.log
URL="http://${HOST}:${PORT}"

if [[ -f "${PID_FILE}" ]] && kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; then
  echo "已在运行（PID $(cat "${PID_FILE}")）：${URL}"; exit 0
fi
rm -f "${PID_FILE}"

[[ -x .venv/bin/uvicorn ]] || { echo "缺少 .venv：先运行 uv venv .venv --python 3.13 && uv pip install --python .venv/bin/python -r requirements/app.txt"; exit 1; }
[[ -f data/processed/lol_bp.sqlite3 ]] || { echo "缺少本地数据库：先运行 python3 scripts/build_dataset.py"; exit 1; }
if lsof -ti "tcp:${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "端口 ${PORT} 已被其他程序占用，可用 PORT=8001 ./start.sh 换端口"; exit 1
fi

# Build the frontend if dist is missing or any source file is newer than it.
if [[ ! -f web/dist/index.html ]] || [[ -n "$(find web/src web/index.html web/package.json -newer web/dist/index.html -print -quit)" ]]; then
  echo "构建前端…"
  [[ -d web/node_modules ]] || (cd web && npm install --silent)
  (cd web && npm run build --silent) >/dev/null
fi

mkdir -p data/app
nohup .venv/bin/uvicorn lolbp.api:app --host "${HOST}" --port "${PORT}" >"${LOG_FILE}" 2>&1 &
echo $! >"${PID_FILE}"

for _ in $(seq 1 30); do
  if curl -fs "${URL}/api/meta" >/dev/null 2>&1; then
    echo "已启动（PID $(cat "${PID_FILE}")）：${URL}"
    echo "日志：${LOG_FILE}；关闭：./stop.sh"
    [[ "${OPEN:-1}" == 1 ]] && command -v open >/dev/null && open "${URL}"
    exit 0
  fi
  if ! kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; then break; fi
  sleep 0.5
done
echo "启动失败，日志最后几行："; tail -n 20 "${LOG_FILE}"; rm -f "${PID_FILE}"; exit 1
