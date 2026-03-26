#!/bin/bash
# Setup script for Weather MCP Server

set -e

echo "🚀 Setting up Weather MCP Server..."

# Check Python version
echo "🔍 Checking Python version..."
python3 --version || { echo "❌ Python 3 is required"; exit 1; }

# Create virtual environment
echo "📦 Creating virtual environment..."
python3 -m venv venv || { echo "❌ Failed to create virtual environment"; exit 1; }

# Activate virtual environment
echo "⚡ Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "📝 Creating .env file from template..."
    cp .env.example .env
    echo ""
    echo "⚠️  Please edit .env file and add your API keys:"
    echo "   - OPENWEATHERMAP_API_KEY from https://openweathermap.org/api"
    echo "   - WEATHERAPI_API_KEY from https://www.weatherapi.com/"
    echo "   - VISUALCROSSING_API_KEY from https://www.visualcrossing.com/weather-api"
    echo ""
    echo "You need at least one API key for the server to work."
fi

# Make scripts executable
chmod +x weather_server.py
chmod +x test_server.py

# Test the server
echo "🧪 Testing the server..."
if python3 test_server_updated.py; then
    echo ""
    echo "✅ Setup completed successfully!"
    echo ""
    echo "To use with Claude Desktop:"
    echo "1. Add the following to ~/.claude/mcp.json:"
    echo ""
    cat << EOF
{
  "mcpServers": {
    "weather-server": {
      "command": "$(pwd)/venv/bin/python3",
      "args": ["$(pwd)/weather_server_fixed.py"]
    }
  }
}
EOF
    echo ""
    echo "2. Restart Claude Desktop"
    echo ""
    echo "3. Ask Claude: 'What's the weather in Tokyo?'"
    echo ""
    echo "To run the server manually:"
    echo "  source venv/bin/activate"
    echo "  python3 weather_server_fixed.py"
else
    echo "❌ Setup failed during testing"
    exit 1
fi