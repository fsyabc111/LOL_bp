#!/usr/bin/env bash
# Stop the app started by ./start.sh.
set -euo pipefail
cd "$(dirname "$0")"

PID_FILE=data/app/server.pid
if [[ ! -f "${PID_FILE}" ]]; then echo "没有在运行（找不到 ${PID_FILE}）"; exit 0; fi
PID="$(cat "${PID_FILE}")"
if ! kill -0 "${PID}" 2>/dev/null; then echo "进程 ${PID} 已不存在，清理 PID 文件"; rm -f "${PID_FILE}"; exit 0; fi
# Only stop it if it is still our uvicorn (the PID could have been reused).
if ! ps -p "${PID}" -o command= | grep -q "uvicorn lolbp.api:app"; then
  echo "PID ${PID} 不是本应用的服务，未处理；已清理 PID 文件"; rm -f "${PID_FILE}"; exit 1
fi

kill "${PID}"
for _ in $(seq 1 20); do
  kill -0 "${PID}" 2>/dev/null || { rm -f "${PID_FILE}"; echo "已关闭（PID ${PID}）"; exit 0; }
  sleep 0.5
done
echo "10 秒内未退出，强制结束"; kill -9 "${PID}" 2>/dev/null || true; rm -f "${PID_FILE}"
