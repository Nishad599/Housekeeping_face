#!/bin/bash
# Script to stop the Face Attendance System

PORT=${1:-8005}

# Kill by saved PID if available
if [ -f app.pid ]; then
    PID=$(cat app.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "🛑 Stopping Face Attendance System (PID: $PID)..."
        kill $PID
        sleep 1
        if ps -p $PID > /dev/null 2>&1; then
            echo "⚠️ Forcing kill..."
            kill -9 $PID 2>/dev/null
        fi
        echo "✅ App stopped (PID: $PID)."
    else
        echo "Process not running, cleaning stale pid file."
    fi
    rm -f app.pid
fi

# Always also kill anything still holding the port (cleans up orphan processes)
if command -v fuser &>/dev/null; then
    ORPHAN=$(fuser ${PORT}/tcp 2>/dev/null)
    if [ -n "$ORPHAN" ]; then
        echo "🧹 Cleaning up orphan process on port $PORT (PID: $ORPHAN)..."
        fuser -k ${PORT}/tcp 2>/dev/null
        sleep 1
    fi
elif command -v lsof &>/dev/null; then
    ORPHAN=$(lsof -t -i:${PORT} 2>/dev/null)
    if [ -n "$ORPHAN" ]; then
        echo "🧹 Cleaning up orphan process on port $PORT (PID: $ORPHAN)..."
        kill -9 $ORPHAN 2>/dev/null
        sleep 1
    fi
fi

echo "✅ Port $PORT is free."
