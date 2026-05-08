#!/bin/bash
# Image Exporter Startup Script

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Starting Image Exporter Web UI...${NC}"

# Change to the application directory
cd /home/nutanix/web-images

# Check if app.py exists
if [ ! -f "app.py" ]; then
    echo -e "${RED}❌ Error: app.py not found in $(pwd)${NC}"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment not found. Please run the installation steps first.${NC}"
    exit 1
fi

# Activate virtual environment and run the app
echo -e "${GREEN}✅ Activating environment and launching app...${NC}"
source .venv/bin/activate

# Use gunicorn for a better experience or just python for foreground
echo -e "${YELLOW}🌐 Dashboard will be available at: http://$(hostname -I | awk '{print $1}'):5000${NC}"
echo -e "${YELLOW}⌨️  Press Ctrl+C to stop the server${NC}"
echo ""

python3 app.py
