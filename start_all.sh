#!/bin/bash

# ==============================================================================
# 本地生活助手 2.0 - 全栈服务一键启动 (静默模式 - 最终修复版)
# ==============================================================================

# 配置区域
pick_existing_dir() {
    local existing_value="$1"
    shift

    if [ -n "$existing_value" ] && [ -d "$existing_value" ]; then
        echo "$existing_value"
        return 0
    fi

    local candidate
    for candidate in "$@"; do
        if [ -d "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done

    return 1
}

pick_exe_dir() {
    local existing_value="$1"
    local exe_name="$2"
    shift 2

    if [ -n "$existing_value" ] && [ -x "$existing_value/$exe_name" ]; then
        echo "$existing_value"
        return 0
    fi

    local candidate
    for candidate in "$@"; do
        if [ -x "$candidate/$exe_name" ]; then
            echo "$candidate"
            return 0
        fi
    done

    if command -v "$exe_name" >/dev/null 2>&1; then
        dirname "$(command -v "$exe_name")"
        return 0
    fi

    return 1
}

MYSQL_SERVICE_NAME="${MYSQL_SERVICE_NAME:-mysql}"
REDIS_DIR="$(pick_exe_dir "${REDIS_DIR:-}" "redis-server.exe" \
    "D:/software/redis/Redis-x64-5.0.14.1" \
    "C:/Program Files/Redis" \
    "C:/Program Files/RedisStack")" || REDIS_DIR=""
POSTGRES_DIR="$(pick_existing_dir "${POSTGRES_DIR:-}" \
    "D:/software/PostgreSQL/16" \
    "C:/Program Files/PostgreSQL/16" \
    "C:/Program Files/PostgreSQL/17")" || POSTGRES_DIR=""
QDRANT_DIR="$(pick_exe_dir "${QDRANT_DIR:-}" "qdrant.exe" \
    "D:/software/qdrant" \
    "C:/Program Files/Qdrant" \
    "C:/Program Files/qdrant")" || QDRANT_DIR=""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if command -v cygpath >/dev/null 2>&1; then
    ROOT_DIR="$(cygpath -w "$SCRIPT_DIR")"
else
    ROOT_DIR="$SCRIPT_DIR"
fi
FRONTEND_DIR="$ROOT_DIR/frontend"
AI_SERVICE_DIR="$ROOT_DIR/learning-agent-service"
if command -v cygpath >/dev/null 2>&1; then
    AI_SERVICE_DIR_POSIX="$(cygpath -u "$AI_SERVICE_DIR")"
else
    AI_SERVICE_DIR_POSIX="$(printf '%s\n' "$AI_SERVICE_DIR" | sed 's#\\#/#g')"
fi
OPENAI_ENV_FILE="$AI_SERVICE_DIR_POSIX/.env"
AI_SERVICE_LOG_DIR="$AI_SERVICE_DIR_POSIX/var/local-logs"
AI_SERVICE_LOG="$AI_SERVICE_LOG_DIR/python-service.log"
QDRANT_LOG="$AI_SERVICE_LOG_DIR/qdrant.log"
POSTGRES_LOG="$AI_SERVICE_LOG_DIR/postgres_ctl.log"
QDRANT_HEALTH_URL="http://127.0.0.1:6333/healthz"
START_ALL_FOLLOW_PYTHON_LOGS="${START_ALL_FOLLOW_PYTHON_LOGS:-1}"

if [ -n "$POSTGRES_DIR" ]; then
    if [ -n "${POSTGRES_BIN_DIR:-}" ] && [ -x "$POSTGRES_BIN_DIR/pg_ctl.exe" ]; then
        :
    elif [ -x "$POSTGRES_DIR/Server/bin/pg_ctl.exe" ]; then
        POSTGRES_BIN_DIR="$POSTGRES_DIR/Server/bin"
    elif [ -x "$POSTGRES_DIR/bin/pg_ctl.exe" ]; then
        POSTGRES_BIN_DIR="$POSTGRES_DIR/bin"
    else
        POSTGRES_BIN_DIR="$POSTGRES_DIR/Server/bin"
    fi

    if [ -n "${POSTGRES_DATA_DIR:-}" ] && [ -d "$POSTGRES_DATA_DIR" ]; then
        :
    elif [ -d "$POSTGRES_DIR/Data" ]; then
        POSTGRES_DATA_DIR="$POSTGRES_DIR/Data"
    elif [ -d "$POSTGRES_DIR/data" ]; then
        POSTGRES_DATA_DIR="$POSTGRES_DIR/data"
    else
        POSTGRES_DATA_DIR="$POSTGRES_DIR/Data"
    fi

    POSTGRES_CTL="$POSTGRES_BIN_DIR/pg_ctl.exe"
else
    POSTGRES_BIN_DIR="${POSTGRES_BIN_DIR:-}"
    POSTGRES_DATA_DIR="${POSTGRES_DATA_DIR:-}"
    POSTGRES_CTL="${POSTGRES_CTL:-}"
fi

QDRANT_EXE="$QDRANT_DIR/qdrant.exe"

mkdir -p "$AI_SERVICE_LOG_DIR"

# 定义颜色
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

read_env_file_value() {
    local file="$1"
    local key="$2"

    python - "$file" "$key" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
key = sys.argv[2]

if not path.is_file():
    sys.exit(1)

for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export "):
        line = line[len("export "):].lstrip()
    if "=" not in line:
        continue
    current_key, value = line.split("=", 1)
    if current_key.strip() != key:
        continue
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    if value:
        print(value)
        sys.exit(0)

sys.exit(1)
PY
}

resolve_openai_key_source() {
    local key_name
    for key_name in LEARNING_AGENT_OPENAI_API_KEY AI_API_KEY OPENAI_API_KEY; do
        if read_env_file_value "$OPENAI_ENV_FILE" "$key_name" >/dev/null 2>&1; then
            echo ".env"
            return 0
        fi
    done

    for key_name in LEARNING_AGENT_OPENAI_API_KEY AI_API_KEY OPENAI_API_KEY; do
        if [ -n "${!key_name:-}" ]; then
            echo "系统环境变量"
            return 0
        fi
    done

    echo "未配置"
}

wait_for_health() {
    local label="$1"
    local url="$2"
    local max_attempts="${3:-30}"

    echo -e "    正在等待 ${label} 就绪..."
    for _ in $(seq 1 "$max_attempts"); do
        if curl -fsS "$url" >/dev/null 2>&1; then
            echo -e "    ${GREEN}[OK] ${label} 已就绪。${NC}"
            return 0
        fi
        sleep 1
    done

    echo -e "    ${YELLOW}[Warn] 等待 ${label} 超时，请检查服务日志。${NC}"
    return 1
}

wait_for_port() {
    local port="$1"
    local label="$2"
    local max_attempts="${3:-30}"

    echo -e "    正在等待 ${label} 就绪..."
    for _ in $(seq 1 "$max_attempts"); do
        if netstat -ano | grep -q -E ":${port}[[:space:]]"; then
            echo -e "    ${GREEN}[OK] ${label} 已就绪。${NC}"
            return 0
        fi
        sleep 1
    done

    echo -e "    ${YELLOW}[Warn] 等待 ${label} 超时，请检查 PostgreSQL 日志。${NC}"
    return 1
}

log_health_status() {
    local label="$1"
    local url="$2"
    local degraded_reason="$3"

    if curl -fsS "$url" >/dev/null 2>&1; then
        echo -e "    ${GREEN}[Health] ${label} 健康状态：正常。${NC}"
    else
        echo -e "    ${YELLOW}[Health] ${label} 健康状态：异常。降级原因：${degraded_reason}${NC}"
    fi
}

read_postmaster_pid() {
    local pid_file="$1"
    local pid

    if [ ! -f "$pid_file" ]; then
        return 1
    fi

    pid="$(head -n 1 "$pid_file" 2>/dev/null | tr -d '[:space:]\r')"
    if [[ "$pid" =~ ^[0-9]+$ ]]; then
        echo "$pid"
        return 0
    fi

    return 1
}

postgres_pid_state() {
    local pid="$1"

    if [ -z "$pid" ]; then
        echo "missing"
        return 0
    fi

    if command -v powershell.exe >/dev/null 2>&1; then
        if powershell.exe -NoProfile -Command "try { \$process = Get-CimInstance Win32_Process -Filter \"ProcessId=$pid\" -ErrorAction Stop; if (\$null -eq \$process) { exit 1 }; if (\$process.Name -ieq 'postgres.exe') { exit 0 } else { exit 2 } } catch { exit 3 }" >/dev/null 2>&1; then
            echo "running"
            return 0
        fi

        case $? in
            1) echo "stale" ;;
            2) echo "other_process" ;;
            *) echo "unknown" ;;
        esac
        return 0
    fi

    if command -v tasklist.exe >/dev/null 2>&1; then
        if tasklist.exe /FI "PID eq $pid" 2>/dev/null | grep -qi "postgres.exe"; then
            echo "running"
        else
            echo "stale"
        fi
        return 0
    fi

    echo "unknown"
    return 0
}

# ==============================================================================
# 停止旧服务阶段 (干净启动)
# ==============================================================================
echo -e "${YELLOW}>>> 正在清理并停止旧的运行服务...${NC}"

# 1. 停止 Vue 前端 (3001)
echo -e "    正在关闭 3001 端口 (Vue 前端) 以及相关僵尸进程..."
powershell.exe -NoProfile -Command '$p = Get-NetTCPConnection -LocalPort 3001 -ErrorAction SilentlyContinue; if($p) { foreach($conn in $p) { if($conn.OwningProcess -ne 0) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue } } }; Get-CimInstance Win32_Process | ? { $_.CommandLine -match "vite" -or $_.CommandLine -match "npm run dev" } | % { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }'

# 2. 停止 AI 服务 (8000)
echo -e "    正在关闭 8000 端口 (Python AI 服务) 以及相关僵尸进程..."
powershell.exe -NoProfile -Command '$p = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue; if($p) { foreach($conn in $p) { if($conn.OwningProcess -ne 0) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue } } }; Get-CimInstance Win32_Process | ? { $_.CommandLine -match "uvicorn" -or $_.CommandLine -match "local_life" } | % { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }'

# 3. 停止 Qdrant (6333) —— 仅当不健康时才重启，保留健康中的实例（与 Redis/MySQL 策略保持一致）
echo -e "    检查 6333 端口 (Qdrant)..."
if curl -fsS "$QDRANT_HEALTH_URL" > /dev/null 2>&1; then
    echo -e "    ${BLUE}[跳过] Qdrant 已在运行且健康，保留现有实例。${NC}"
else
    # 不健康或未运行，杀掉僵尸进程，让启动阶段重新拉起
    powershell.exe -NoProfile -Command '$p = Get-NetTCPConnection -LocalPort 6333 -ErrorAction SilentlyContinue; if($p) { foreach($conn in $p) { if($conn.OwningProcess -ne 0) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue } } }'
fi

# 4. 停止 Redis (6379)
echo -e "    检查 6379 端口 (Redis)..."
if netstat -ano | grep -q -E ":6379[[:space:]]"; then
    echo -e "    ${BLUE}[跳过] Redis 已在运行，保留现有实例。${NC}"
else
    echo -e "    Redis 未运行，无需停止。"
fi

# 5. 停止 MySQL (3306)
echo -e "    检查 MySQL 数据库服务 ($MYSQL_SERVICE_NAME)..."
if netstat -ano | grep -q -E ":3306[[:space:]]"; then
    echo -e "    ${BLUE}[跳过] MySQL 已在运行，保留现有实例。${NC}"
else
    echo -e "    MySQL 未运行，无需停止。"
fi

# 6. 停止 PostgreSQL (5432)
echo -e "    检查 PostgreSQL 数据库 (5432)..."
if netstat -ano | grep -q -E ":5432[[:space:]]"; then
    echo -e "    ${BLUE}[跳过] PostgreSQL 已在监听 5432 端口，保留现有实例。${NC}"
else
    echo -e "    PostgreSQL 5432 端口未监听，正在清理可能残留的僵尸进程与锁文件..."
    taskkill /F /IM postgres.exe 2>/dev/null || true
    if [ -f "$POSTGRES_DATA_DIR/postmaster.pid" ]; then
        rm -f "$POSTGRES_DATA_DIR/postmaster.pid"
    fi
fi

echo -e "    ${GREEN}[OK] 旧服务清理完成。${NC}"
echo -e "----------------------------------------------------"

echo -e "${BLUE}>>> 正在启动 本地生活助手 2.0 全系统服务...${NC}"
echo -e "${BLUE}OpenRouter key 实际来源：$(resolve_openai_key_source)${NC}"
echo -e "    说明：.env 配置优先；如果 .env 没有可用 key，或请求返回 401/403，会回退到系统环境变量。"

# 1. 启动 PostgreSQL
echo -e "${BLUE}[1/6] 检查 PostgreSQL (5432)...${NC}"
if ! netstat -ano | grep -q -E ":5432[[:space:]]"; then
    if [ -n "$POSTGRES_DATA_DIR" ] && [ -d "$POSTGRES_DATA_DIR" ]; then
        POSTMASTER_PID_FILE="$POSTGRES_DATA_DIR/postmaster.pid"
        
        # 再次确保没有残留的 lock 文件以防万一
        if [ -f "$POSTMASTER_PID_FILE" ]; then
            echo -e "    ${YELLOW}[Warn] 检测到残留的 postmaster.pid 文件，正在强行清理...${NC}"
            rm -f "$POSTMASTER_PID_FILE"
        fi
        
        echo -e "    正在启动 PostgreSQL..."
        if [ -n "$POSTGRES_CTL" ] && [ -f "$POSTGRES_CTL" ]; then
            "$POSTGRES_CTL" start -D "$POSTGRES_DATA_DIR" -l "$POSTGRES_LOG" -w
        else
            echo -e "    ${YELLOW}[Warn] 未找到 pg_ctl.exe，尝试直接用 postgres.exe 隐式拉起数据库...${NC}"
            if [ -n "$POSTGRES_BIN_DIR" ] && [ -f "$POSTGRES_BIN_DIR/postgres.exe" ]; then
                powershell.exe -NoProfile -Command "Start-Process '$POSTGRES_BIN_DIR/postgres.exe' -ArgumentList '-D \"$POSTGRES_DATA_DIR\"' -WindowStyle Hidden"
            else
                echo -e "    ${YELLOW}[Warn] 未找到 PostgreSQL 可执行文件，跳过自动启动。${NC}"
            fi
        fi
        
        wait_for_port 5432 "PostgreSQL (5432)" 15
    else
        echo -e "    ${YELLOW}[Warn] 未找到 PostgreSQL 数据目录，跳过自动启动。可通过环境变量 POSTGRES_DIR / POSTGRES_BIN_DIR / POSTGRES_DATA_DIR 覆盖。${NC}"
    fi
fi
echo -e "    ${GREEN}[OK] PostgreSQL 已就绪。${NC}"

# 2. 启动 MySQL
echo -e "${BLUE}[2/6] 检查 MySQL (3306)...${NC}"
if ! netstat -ano | grep -q -E ":3306[[:space:]]"; then
    powershell.exe -NoProfile -Command "Start-Process cmd -ArgumentList '/c net start $MYSQL_SERVICE_NAME' -Verb RunAs"
    sleep 3
fi
echo -e "    ${GREEN}[OK] MySQL 已就绪。${NC}"

# 3. 启动 Redis
echo -e "${BLUE}[3/6] 检查 Redis (6379)...${NC}"
if ! netstat -ano | grep -q -E ":6379[[:space:]]"; then
    if [ -n "$REDIS_DIR" ] && [ -x "$REDIS_DIR/redis-server.exe" ]; then
        powershell.exe -NoProfile -Command "Start-Process '$REDIS_DIR/redis-server.exe' -ArgumentList 'redis.windows.conf' -WorkingDirectory '$REDIS_DIR' -WindowStyle Hidden"
        sleep 2
    else
        echo -e "    ${YELLOW}[Warn] 未找到 Redis 安装目录或 redis-server.exe，跳过自动启动。可通过环境变量 REDIS_DIR 覆盖。${NC}"
    fi
fi
echo -e "    ${GREEN}[OK] Redis 已就绪。${NC}"

# 4. 启动 Qdrant
echo -e "${BLUE}[4/6] 检查 Qdrant (6333)...${NC}"
qdrant_degraded_reason="Qdrant 未能通过 /healthz，记忆层会降级到 fallback/noop。"
if curl -fsS "$QDRANT_HEALTH_URL" >/dev/null 2>&1; then
    echo -e "    ${BLUE}[跳过] Qdrant 已在运行，保留现有实例。${NC}"
else
    if [ -n "$QDRANT_DIR" ] && [ -x "$QDRANT_EXE" ] && [ -d "$QDRANT_DIR" ]; then
        : > "$QDRANT_LOG"
        echo -e "    ${BLUE}正在启动 Qdrant，记忆层会根据它的健康状态决定是否降级。${NC}"
        (
            cd "$QDRANT_DIR"
            nohup ./qdrant.exe >"$QDRANT_LOG" 2>&1 &
        )
        sleep 2
        if wait_for_health "Qdrant (6333)" "$QDRANT_HEALTH_URL" 20; then
            qdrant_degraded_reason="Qdrant 健康检查通过，记忆层可使用真实后端。"
        else
            qdrant_degraded_reason="Qdrant 启动后仍无法通过 /healthz，记忆层会降级到 fallback/noop。"
        fi
    else
        qdrant_degraded_reason="缺少 Qdrant 安装目录或 qdrant.exe，记忆层会降级到 fallback/noop。"
        echo -e "    ${YELLOW}[Warn] 未找到 Qdrant 安装目录或 qdrant.exe，真实记忆后端不可用。可通过环境变量 QDRANT_DIR 覆盖。${NC}"
    fi
fi
log_health_status "Qdrant" "$QDRANT_HEALTH_URL" "$qdrant_degraded_reason"

# 5. 启动 AI 服务
echo -e "${BLUE}[5/6] 检查 AI 服务 (8000)...${NC}"
if ! netstat -ano | grep -q -E ":8000[[:space:]]"; then
    mkdir -p "$AI_SERVICE_LOG_DIR"
    : > "$AI_SERVICE_LOG"
    echo -e "    ${BLUE}正在启动 AI 服务...${NC}"
    powershell.exe -NoProfile -Command "Start-Process cmd -ArgumentList '/c start_python.bat' -WorkingDirectory '$AI_SERVICE_DIR' -WindowStyle Hidden"
    sleep 2
fi
if ! wait_for_health "AI 服务 (8000)" "http://127.0.0.1:8000/health" 60; then
    echo -e "    ${YELLOW}[Warn] AI 服务日志请查看：${AI_SERVICE_LOG} 和 ${AI_SERVICE_LOG_DIR}/python-service-bootstrap.log${NC}"
fi

# 6. 启动 Vue 前端
echo -e "${BLUE}[6/6] 正在后台启动 Vue 前端 (3001)...${NC}"
if [ -d "$FRONTEND_DIR" ]; then
    if ! command -v npm >/dev/null 2>&1; then
        echo -e "    ${YELLOW}[Error] 未找到 npm，请先安装 Node.js 再启动前端。${NC}"
    else
        # 修复：排除 PID 0 且忽略停止进程的报错
        powershell.exe -NoProfile -Command '$p = Get-NetTCPConnection -LocalPort 3001 -ErrorAction SilentlyContinue; if($p -and $p.OwningProcess -ne 0) { Stop-Process -Id $p.OwningProcess -Force -ErrorAction SilentlyContinue }'
        # 启动前端
        powershell.exe -NoProfile -Command "Start-Process cmd -ArgumentList '/c npm run dev' -WorkingDirectory '$FRONTEND_DIR' -WindowStyle Hidden"
        sleep 3
        if netstat -ano | grep -q -E ":3001[[:space:]]"; then
            echo -e "    ${GREEN}[OK] 前端已在后台启动。${NC}"
        else
            echo -e "    ${YELLOW}[Warn] 已发起前端启动，但端口 3001 还未监听，请检查 frontend 依赖或控制台日志。${NC}"
        fi
    fi
else
    echo -e "    ${YELLOW}[Error] 未找到 frontend 目录。${NC}"
fi

echo -e "----------------------------------------------------"
echo -e "${GREEN}>>> 所有服务已在后台就绪！${NC}"
echo -e "${YELLOW}当前状态：${NC}"
echo -e "    - PostgreSQL 地址: 127.0.0.1:5432 (注意：这是数据库二进制端口，请使用 DBeaver/Navicat 等客户端连接，请勿在浏览器直接访问)"
echo -e "    - PostgreSQL 数据库: learning_agent"
echo -e "    - Qdrant API 接口: http://127.0.0.1:6333 (直接访问返回 JSON 为正常现象)"
echo -e "    - Qdrant 可视化面板: http://127.0.0.1:6333/dashboard (可在浏览器中直接打开进行管理)"
echo -e "    - 前端地址: http://localhost:3001"
echo -e "    - 后端接口: http://localhost:8081"
echo -e ""
echo -e "${BLUE}>>> 请在 IDE 中启动 Java 主程序 (HmDianPingApplication)。${NC}"
echo -e "----------------------------------------------------"

follow_python_service_logs() {
    local bootstrap_log="$AI_SERVICE_LOG_DIR/python-service-bootstrap.log"
    local stdout_log="$AI_SERVICE_LOG_DIR/python-service.out.log"
    local stderr_log="$AI_SERVICE_LOG"

    echo -e "${BLUE}>>> 正在跟随 Python 服务日志，按 Ctrl+C 退出日志跟随。${NC}"
    echo -e "    - $bootstrap_log"
    echo -e "    - $stdout_log"
    echo -e "    - $stderr_log"
    tail -n 20 -F "$bootstrap_log" "$stdout_log" "$stderr_log"
}

if [ "$START_ALL_FOLLOW_PYTHON_LOGS" != "0" ]; then
    follow_python_service_logs
fi
