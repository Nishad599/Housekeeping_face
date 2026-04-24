#!/bin/bash
# Script to start the Face Attendance System in the background

PORT=${1:-8005}

echo "🚀 Starting Face Attendance System in background on port $PORT..."

# Run the system using nohup
# We use the existing run.sh logic
nohup ./run.sh $PORT > output.log 2>&1 &

# Save the PID
PID=$!
echo $PID > app.pid

echo "✅ App is running in background (PID: $PID)"
echo "📄 Logs are being written to output.log"
echo "🛑 To stop the app, run: ./stop.sh"
