#!/bin/bash
# start_services.sh
# Bash Startup Script for hm-dianping Local Life Project
#
# Starts MySQL, Redis, Frontend (Next.js), and Python Agent services.
# Cleans up existing Python and Frontend processes before starting.

# Exit on error
set -e

# Define colors for terminal output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}==========================================================${NC}"
echo -e "${CYAN}          Starting Local Life Project Services            ${NC}"
echo -e "${CYAN}==========================================================${NC}"

# Helper function to check if a port is listening
check_port() {
    local port=$1
    if command -v lsof >/dev/null 2>&1; then
        lsof -i :$port -sTCP:LISTEN >/dev/null 2>&1
        return $?
    elif command -v netstat >/dev/null 2>&1; then
        netstat -ano | grep -i listening | grep -q -E ":$port[[:space:]]|:$port$"
        return $?
    else
        # Fallback to bash tcp connection check if netstat/lsof are missing
        (echo > /dev/tcp/127.0.0.1/$port) >/dev/null 2>&1
        return $?
    fi
}

# Helper function to kill process on a port
kill_port() {
    local port=$1
    local name=$2
    local pid=""

    if command -v lsof >/dev/null 2>&1; then
        pid=$(lsof -t -i :$port 2>/dev/null | head -n 1)
    elif command -v netstat >/dev/null 2>&1; then
        # Check standard netstat or Windows-style netstat under Git Bash
        pid=$(netstat -ano | grep -i listening | grep -E ":$port[[:space:]]" | awk '{print $NF}' | tr -d '\r' | head -n 1)
        if [ -z "$pid" ] || [ "$pid" = "0" ]; then
            pid=$(netstat -ano | grep LISTENING | grep ":$port " | awk '{print $5}' | tr -d '\r' | head -n 1)
        fi
    fi

    if [ -n "$pid" ] && [ "$pid" != "0" ]; then
        echo -e "  Found existing $name on port $port (PID: $pid)."
        echo -e "  ${YELLOW}Stopping process $pid...${NC}"
        
        # Cross-platform kill handling for Git Bash/Windows & Unix
        if expr "$OSTYPE" : "msys" >/dev/null || expr "$OSTYPE" : "cygwin" >/dev/null; then
            taskkill //F //PID "$pid" >/dev/null 2>&1 || kill -9 "$pid" >/dev/null 2>&1 || true
        else
            kill -9 "$pid" >/dev/null 2>&1 || true
        fi
        sleep 1
        echo -e "  ${GREEN}Successfully stopped $name on port $port.${NC}"
    else
        echo -e "  ${GREEN}No running $name found on port $port.${NC}"
    fi
}

# --------------------------------------------------------
# 1. Stop Existing Python and Frontend Services
# --------------------------------------------------------
echo -e "${CYAN}[1/5] Checking for running Frontend and Python processes...${NC}"

# Python Service (Port 8000)
kill_port 8000 "Python Service"

# Frontend Service (Port 3000)
kill_port 3000 "Frontend Service"

# --------------------------------------------------------
# 2. Check & Start MySQL (Port 3306)
# --------------------------------------------------------
echo -e "${CYAN}[2/5] Checking MySQL (Port 3306)...${NC}"
if check_port 3306; then
    echo -e "  ${GREEN}MySQL is already running.${NC}"
else
    echo -e "  ${YELLOW}MySQL is not running. Attempting to start service...${NC}"
    started=false
    # Windows platform service starts
    if expr "$OSTYPE" : "msys" >/dev/null || expr "$OSTYPE" : "cygwin" >/dev/null; then
        for service in "MySQL" "MySQL80" "mysql"; do
            if net start "$service" >/dev/null 2>&1; then
                sleep 3
                if check_port 3306; then
                    echo -e "  ${GREEN}MySQL service $service started successfully.${NC}"
                    started=true
                    break
                fi
            fi
        done
    else
        # Linux/macOS platform service starts
        if command -v systemctl >/dev/null 2>&1; then
            sudo systemctl start mysql >/dev/null 2>&1 || sudo systemctl start mariadb >/dev/null 2>&1
        elif command -v brew >/dev/null 2>&1; then
            brew services start mysql >/dev/null 2>&1
        fi
        sleep 3
        if check_port 3306; then
            echo -e "  ${GREEN}MySQL service started successfully.${NC}"
            started=true
        fi
    fi

    if [ "$started" = false ]; then
        echo -e "  ${RED}Could not automatically start MySQL. Please ensure MySQL is running on port 3306.${NC}"
    fi
fi

# --------------------------------------------------------
# 3. Check & Start Redis (Port 6379)
# --------------------------------------------------------
echo -e "${CYAN}[3/5] Checking Redis (Port 6379)...${NC}"
REDIS_HOME="${REDIS_HOME:-/d/software/redis/Redis-x64-5.0.14.1}"
REDIS_SERVER="$REDIS_HOME/redis-server.exe"
REDIS_CONF="$REDIS_HOME/redis.windows.conf"
REDIS_LOG="var/redis_service.log"

if check_port 6379; then
    echo -e "  ${GREEN}Redis is already running.${NC}"
    if [ -f "scripts/init_redis_stream.py" ]; then
        python scripts/init_redis_stream.py
    fi
else
    if [ ! -f "$REDIS_SERVER" ]; then
        echo -e "  ${RED}Redis is not running and redis-server.exe was not found at: $REDIS_SERVER${NC}"
        exit 1
    fi

    echo -e "  ${YELLOW}Redis is not running. Starting real Redis from: $REDIS_HOME${NC}"
    mkdir -p var
    "$REDIS_SERVER" "$REDIS_CONF" > "$REDIS_LOG" 2>&1 &

    for i in {1..10}; do
        sleep 1
        if check_port 6379; then
            echo -e "  ${GREEN}Redis started successfully.${NC}"
            if [ -f "scripts/init_redis_stream.py" ]; then
                python scripts/init_redis_stream.py
            fi
            break
        fi
    done

    if ! check_port 6379; then
        echo -e "  ${RED}Failed to start Redis. Check $REDIS_LOG for details.${NC}"
        exit 1
    fi
fi

# Create var directory for logs if not exists
mkdir -p var

# --------------------------------------------------------
# 4. Start Python AI Agent Service (Port 8000)
# --------------------------------------------------------
echo -e "${CYAN}[4/5] Launching Python AI Agent Service (Port 8000)...${NC}"
python_log="var/python_service.log"
python_log_abs="$(cd "$(dirname "$python_log")" && pwd)/$(basename "$python_log")"
python_log_url="file://$python_log_abs"
# Start Python web app using Uvicorn in background
python -m uvicorn local_life_agent.app:app --host 127.0.0.1 --port 8000 > "$python_log" 2>&1 &
# Wait up to 5 seconds for the port to bind
for i in {1..5}; do
    if check_port 8000; then
        break
    fi
    sleep 1
done

if check_port 8000; then
    echo -e "  ${GREEN}Python AI Agent Service is now running in the background.${NC}"
    echo -e "  ${YELLOW}Service: http://127.0.0.1:8000${NC}"
    echo -e "  ${YELLOW}Logs: $python_log_abs${NC}"
    echo -e "  ${YELLOW}Log link: $python_log_url${NC}"
else
    echo -e "  ${RED}Failed to start Python AI Agent Service.${NC}"
    echo -e "  ${RED}Check logs at: $python_log_abs${NC}"
    echo -e "  ${RED}Log link: $python_log_url${NC}"
fi

# --------------------------------------------------------
# 5. Start Frontend Service (Port 3000)
# --------------------------------------------------------
echo -e "${CYAN}[5/5] Launching Frontend Service (Port 3000)...${NC}"
if [ -d "frontend" ]; then
    if command -v npm >/dev/null 2>&1; then
        # Start Next.js frontend dev server in background
        (cd frontend && npm run dev > ../var/frontend_service.log 2>&1 &)
        sleep 3
        if check_port 3000; then
            echo -e "  ${GREEN}Frontend Service is running.${NC}"
        else
            echo -e "  ${YELLOW}Frontend dev server launched. (Port 3000 might take a few seconds to bind)${NC}"
        fi
    else
        echo -e "  ${RED}npm is not installed. Cannot start Frontend service automatically.${NC}"
    fi
else
    echo -e "  ${RED}frontend directory not found.${NC}"
fi

echo -e "${CYAN}==========================================================${NC}"
echo -e "${GREEN}>>> Startup complete! Please start your Java backend in IDE.${NC}"
echo -e "${GREEN}>>> Frontend address: http://localhost:3000${NC}"
echo -e "${CYAN}==========================================================${NC}"

# Clickable link in last line as requested
echo "http://localhost:3000"
