#!/bin/bash
# DailyBriefer Setup Script for Oracle Linux (or any Linux VPS)
# Run this ONCE after creating your server:
#   chmod +x setup.sh && sudo ./setup.sh

set -e

echo "=== DailyBriefer Setup Script ==="
echo ""

# 1. Install Python and dependencies
echo "[1/6] Installing Python and system dependencies..."
sudo dnf update -y
sudo dnf install -y python3 python3-pip python3-devel git curl

# 2. Create app directory
echo "[2/6] Setting up application directory..."
APP_DIR="/opt/daily-briefer"
mkdir -p "$APP_DIR/data"

# 3. Copy project files
echo "[3/6] Installing application..."
cd "$APP_DIR"
pip3 install --user -e .

# 4. Create systemd service
echo "[4/6] Creating systemd service..."
sudo tee /etc/systemd/system/daily-briefer.service > /dev/null << 'EOF'
[Unit]
Description=DailyBriefer - AI News Briefer Agent
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/daily-briefer
Environment=PATH=/root/.local/bin:/usr/bin:/bin
EnvironmentFile=/opt/daily-briefer/.env
ExecStart=/root/.local/bin/daily-briefer poll
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

# 5. Create .env file (user will need to fill in their keys)
echo "[5/6] Creating .env file..."
if [ ! -f "$APP_DIR/.env" ]; then
    cat > "$APP_DIR/.env" << 'EOF'
GMAIL_ADDRESS=your-email@gmail.com
GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx

TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxx

GEMINI_API_KEY=AIzaSy-xxxxxxxxxxxxxxxx
EOF
    echo "  Created $APP_DIR/.env - EDIT THIS FILE WITH YOUR API KEYS!"
else
    echo "  $APP_DIR/.env already exists, skipping."
fi

# 6. Enable and start the service
echo "[6/6] Starting DailyBriefer service..."
sudo systemctl daemon-reload
sudo systemctl enable daily-briefer
sudo systemctl start daily-briefer

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "To check status: sudo systemctl status daily-briefer"
echo "To view logs: sudo journalctl -u daily-briefer -f"
echo "To stop: sudo systemctl stop daily-briefer"
echo "To restart: sudo systemctl restart daily-briefer"
echo ""
echo "IMPORTANT: Edit /opt/daily-briefer/.env with your API keys first!"
