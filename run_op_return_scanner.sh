#!/bin/bash
# Wrapper script for op_return_scanner.py with proper signal handling
# This ensures the script restarts on failure and handles signals gracefully

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="${SCRIPT_DIR}/venv/bin/python3"
SCANNER_SCRIPT="${SCRIPT_DIR}/op_return_scanner.py"
LOG_DIR="${SCRIPT_DIR}/logs"
PID_FILE="${LOG_DIR}/op_return_scanner.pid"

# Create log directory if it doesn't exist
mkdir -p "${LOG_DIR}"

# Function to handle signals
cleanup() {
    echo "$(date): Received signal, shutting down gracefully..."
    if [ -f "${PID_FILE}" ]; then
        PID=$(cat "${PID_FILE}")
        if ps -p "${PID}" > /dev/null 2>&1; then
            kill -TERM "${PID}" 2>/dev/null
            # Wait up to 30 seconds for graceful shutdown
            for i in {1..30}; do
                if ! ps -p "${PID}" > /dev/null 2>&1; then
                    break
                fi
                sleep 1
            done
            # Force kill if still running
            if ps -p "${PID}" > /dev/null 2>&1; then
                kill -KILL "${PID}" 2>/dev/null
            fi
        fi
        rm -f "${PID_FILE}"
    fi
    exit 0
}

# Set up signal handlers
trap cleanup SIGTERM SIGINT

# Check if virtual environment exists
if [ ! -f "${VENV_PYTHON}" ]; then
    echo "Error: Virtual environment not found at ${VENV_PYTHON}"
    echo "Please create it with: python3 -m venv venv"
    exit 1
fi

# Check if scanner script exists
if [ ! -f "${SCANNER_SCRIPT}" ]; then
    echo "Error: Scanner script not found at ${SCANNER_SCRIPT}"
    exit 1
fi

# Main loop - restart on failure
RETRY_COUNT=0
MAX_RETRIES=5
RETRY_DELAY=10

while true; do
    echo "$(date): Starting OP_RETURN scanner..."
    
    # Run the scanner
    "${VENV_PYTHON}" "${SCANNER_SCRIPT}" \
        --continual-scanning \
        --interval 60 \
        --heartbeat 360 \
        >> "${LOG_DIR}/op_return_scanner.log" 2>> "${LOG_DIR}/op_return_scanner_error.log" &
    
    SCANNER_PID=$!
    echo "${SCANNER_PID}" > "${PID_FILE}"
    
    # Wait for the process to finish
    wait "${SCANNER_PID}"
    EXIT_CODE=$?
    
    # Remove PID file
    rm -f "${PID_FILE}"
    
    # Check exit code
    if [ ${EXIT_CODE} -eq 0 ]; then
        echo "$(date): Scanner exited normally (exit code: ${EXIT_CODE})"
        # If it exited normally, don't restart (user may have stopped it)
        break
    else
        RETRY_COUNT=$((RETRY_COUNT + 1))
        echo "$(date): Scanner crashed (exit code: ${EXIT_CODE}), retry ${RETRY_COUNT}/${MAX_RETRIES}"
        
        if [ ${RETRY_COUNT} -ge ${MAX_RETRIES} ]; then
            echo "$(date): Maximum retries reached, giving up"
            exit 1
        fi
        
        echo "$(date): Waiting ${RETRY_DELAY} seconds before restart..."
        sleep ${RETRY_DELAY}
    fi
done

