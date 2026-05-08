#!/bin/bash
# Image Exporter Robust Restart Script
# This script ensures only ONE instance of the dashboard and watchdog runs.

APP_DIR="/home/nutanix/ahv-image-exporter"
PID_FILE="/tmp/ahv-image-exporter-watchdog.pid"
LOG_FILE="/tmp/ahv-image-exporter.log"
PORT=5000

echo "🔄 Initializing Robust Restart for Image Exporter..."

# 1. Kill existing watchdog loop using PID file if it exists
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    echo "🛑 Stopping existing watchdog (PID: $OLD_PID)..."
    kill $OLD_PID 2>/dev/null || true
    rm -f "$PID_FILE"
fi

# 2. Aggressive cleanup of any orphaned processes
echo "🛑 Cleaning up all related processes..."
pkill -9 -f "web-images.*loop" 2>/dev/null || true
pkill -9 -f "gunicorn.*app:app" 2>/dev/null || true

# 3. Ensure the port is actually free
echo "🔍 Verifying port $PORT is clear..."
# Try to kill anything on the port as a last resort
echo "nutanix/4u" | sudo -S fuser -k $PORT/tcp 2>/dev/null || true
sleep 2

# 4. Start the new watchdog loop
echo "🚀 Starting new watchdog loop..."
cd "$APP_DIR"

# Ensure the log file exists
touch "$LOG_FILE"

# The loop is wrapped in a subshell and redirected to the log
# Using exec to replace the shell process with the loop
(
    exec bash -c '
    echo "$$" > "'$PID_FILE'"
    while true; do
        source .venv/bin/activate
        echo "[$(date)] Starting Gunicorn..." >> "'$LOG_FILE'"
        
        gunicorn --bind 0.0.0.0:'$PORT' --workers 4 --timeout 300 \
            --access-logfile /tmp/ahv-image-exporter-access.log
            --error-logfile /tmp/ahv-image-exporter-error.log
            app:app >> "'$LOG_FILE'" 2>&1
            
        EXIT_CODE=$?
        echo "[$(date)] Web UI exited with code $EXIT_CODE. Restarting in 5s..." >> "'$LOG_FILE'"
        sleep 5
    done'
) >/dev/null 2>&1 &

NEW_WATCHDOG=$!
sleep 2

# 5. Final check
if ps -p $NEW_WATCHDOG > /dev/null; then
    echo "✅ Web UI started successfully (Watchdog PID: $NEW_WATCHDOG)"
    echo "📝 Logs: tail -f $LOG_FILE"
    echo "🌐 Dashboard: http://$(hostname -I | awk '{print $1}'):$PORT"
else
    echo "❌ Failed to start watchdog loop. Check $LOG_FILE"
    exit 1
fi
