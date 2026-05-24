#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
LOG_DIR="$ROOT_DIR/var/local-logs"

REDIS_DIR_WIN='D:\software\redis\Redis-x64-5.0.14.1'
QDRANT_DIR_WIN='D:\software\qdrant'

to_posix_path() {
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -u "$1"
  elif command -v wslpath >/dev/null 2>&1; then
    wslpath -u "$1"
  else
    printf '%s\n' "$1"
  fi
}

REDIS_DIR=$(to_posix_path "$REDIS_DIR_WIN")
QDRANT_DIR=$(to_posix_path "$QDRANT_DIR_WIN")
REDIS_EXE="$REDIS_DIR/redis-server.exe"
REDIS_CLI="$REDIS_DIR/redis-cli.exe"
REDIS_CONF="$REDIS_DIR/redis.windows.conf"
QDRANT_EXE="$QDRANT_DIR/qdrant.exe"
REDIS_LOG="$LOG_DIR/redis.log"
QDRANT_LOG="$LOG_DIR/qdrant.log"

mkdir -p "$LOG_DIR"

wait_for_redis() {
  i=0
  while [ "$i" -lt 20 ]; do
    if "$REDIS_CLI" -h 127.0.0.1 -p 6379 ping >/dev/null 2>&1; then
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done
  return 1
}

wait_for_qdrant() {
  i=0
  while [ "$i" -lt 20 ]; do
    if curl -fsS http://127.0.0.1:6333/healthz >/dev/null 2>&1; then
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done
  return 1
}

wait_for_redis_closed() {
  i=0
  while [ "$i" -lt 20 ]; do
    if ! "$REDIS_CLI" -h 127.0.0.1 -p 6379 ping >/dev/null 2>&1; then
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done
  return 1
}

wait_for_qdrant_closed() {
  i=0
  while [ "$i" -lt 20 ]; do
    if ! curl -fsS http://127.0.0.1:6333/healthz >/dev/null 2>&1; then
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done
  return 1
}

stop_by_image() {
  image=$1
  if command -v taskkill >/dev/null 2>&1; then
    taskkill /IM "$image" /T /F >/dev/null 2>&1 || true
    return 0
  fi

  if command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe -NoProfile -Command "Get-Process $image -ErrorAction SilentlyContinue | Stop-Process -Force" >/dev/null 2>&1 || true
  fi
}

stop_redis() {
  if "$REDIS_CLI" -h 127.0.0.1 -p 6379 ping >/dev/null 2>&1; then
    printf '停止 Redis: 127.0.0.1:6379\n'
    "$REDIS_CLI" -h 127.0.0.1 -p 6379 shutdown >/dev/null 2>&1 || true
    sleep 1
  fi
  stop_by_image 'redis-server.exe'
  if wait_for_redis_closed; then
    printf 'Redis 已停止\n'
  else
    printf 'Redis 可能仍在退出中，继续执行启动流程\n'
  fi
}

stop_qdrant() {
  if curl -fsS http://127.0.0.1:6333/healthz >/dev/null 2>&1; then
    printf '停止 Qdrant: http://127.0.0.1:6333\n'
  fi
  stop_by_image 'qdrant.exe'
  if wait_for_qdrant_closed; then
    printf 'Qdrant 已停止\n'
  else
    printf 'Qdrant 可能仍在退出中，继续执行启动流程\n'
  fi
}

start_redis() {
  if "$REDIS_CLI" -h 127.0.0.1 -p 6379 ping >/dev/null 2>&1; then
    printf 'Redis 已经在运行: 127.0.0.1:6379\n'
    return 0
  fi

  printf '启动 Redis: %s\n' "$REDIS_EXE"
  (
    cd "$REDIS_DIR"
    nohup ./redis-server.exe redis.windows.conf >"$REDIS_LOG" 2>&1 &
  )

  if wait_for_redis; then
    printf 'Redis 启动成功: 127.0.0.1:6379\n'
  else
    printf 'Redis 启动失败，请查看日志: %s\n' "$REDIS_LOG" >&2
    exit 1
  fi
}

start_qdrant() {
  if curl -fsS http://127.0.0.1:6333/healthz >/dev/null 2>&1; then
    printf 'Qdrant 已经在运行: http://127.0.0.1:6333\n'
    return 0
  fi

  printf '启动 Qdrant: %s\n' "$QDRANT_EXE"
  (
    cd "$QDRANT_DIR"
    nohup ./qdrant.exe >"$QDRANT_LOG" 2>&1 &
  )

  if wait_for_qdrant; then
    printf 'Qdrant 启动成功: http://127.0.0.1:6333\n'
  else
    printf 'Qdrant 启动失败，请查看日志: %s\n' "$QDRANT_LOG" >&2
    exit 1
  fi
}

start_python_service() {
  if curl -fsS http://127.0.0.1:9000/health >/dev/null 2>&1; then
    printf 'Python 服务已经在运行: http://127.0.0.1:9000\n'
    return 0
  fi

  printf '启动 Python 服务 (learning-agent-service)...\n'
  PYTHON_LOG="$LOG_DIR/python-service.out.log"
  PYTHON_ERR="$LOG_DIR/python-service.err.log"

  if [ ! -f "$ROOT_DIR/.env" ]; then
    if [ -f "$ROOT_DIR/.env.example" ]; then
      cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
      printf '已自动创建 .env 配置文件\n'
    fi
  fi

  (
    cd "$ROOT_DIR"
    export PYTHONPATH="src"
    nohup uvicorn app:app --port 9000 >"$PYTHON_LOG" 2>&1 &
  )

  # 等待服务启动
  i=0
  while [ "$i" -lt 15 ]; do
    if curl -fsS http://127.0.0.1:9000/health >/dev/null 2>&1; then
      printf 'Python 服务启动成功: http://127.0.0.1:9000\n'
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done

  printf 'Python 服务启动较慢或失败，请查看日志: %s\n' "$PYTHON_ERR" >&2
}

stop_python_service() {
  printf '停止 Python 服务 (port 9000)...\n'
  if command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort 9000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id \$_.OwningProcess -Force -ErrorAction SilentlyContinue }" >/dev/null 2>&1 || true
  fi
}

stop_redis
stop_qdrant
stop_python_service
start_redis
start_qdrant
start_python_service

printf '完成。日志目录: %s\n' "$LOG_DIR"
