#!/bin/bash
# Quick start script for Face Attendance System

echo "🚀 Starting Face Attendance System..."
echo "   Shift: 7:00 AM - 4:00 PM"
echo "   OT: After 4:00 PM"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.9+"
    exit 1
fi

# Activate virtual environment
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "❌ venv not found. Please create it: python3 -m venv venv && venv/bin/pip install -r requirements.txt"
    exit 1
fi

# Install dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt --quiet

# Create directories
mkdir -p static/uploads/faces

# Configuration
PORT=${1:-8005}
HOST=${2:-0.0.0.0}

# SSL Support
SSL_OPTS=""
if [ -f "certs/cert.pem" ] && [ -f "certs/key.pem" ]; then
    echo "🔒 SSL Certificates found. Running on HTTPS."
    SSL_OPTS="--ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem"
    PROTOCOL="https"
else
    echo "⚠️ SSL Certificates NOT found. Running on HTTP."
    PROTOCOL="http"
fi

# Start server
echo ""
echo "✅ Starting server on $PROTOCOL://$HOST:$PORT"
echo "   📷 Punch Kiosk: $PROTOCOL://$HOST:$PORT/punch"
echo "   📊 Admin Panel: $PROTOCOL://$HOST:$PORT/login"
echo "   Default login: admin / admin123"
echo ""

uvicorn app.main:app --host $HOST --port $PORT $SSL_OPTS
