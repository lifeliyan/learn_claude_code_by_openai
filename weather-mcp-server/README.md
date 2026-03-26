# Weather MCP Server

A comprehensive Model Context Protocol (MCP) server for weather information with multiple provider support.

## Features

- **Multiple Weather Providers**: OpenWeatherMap, WeatherAPI, VisualCrossing
- **Current Weather**: Temperature, humidity, wind, pressure, visibility, etc.
- **Weather Forecasts**: Multi-day forecasts with detailed information
- **Location Search**: Find locations by name
- **Caching**: In-memory cache to reduce API calls
- **Fallback Support**: Automatic fallback if one provider fails
- **Unit Conversion**: Celsius, Fahrenheit, and Kelvin support
- **Air Quality**: Air quality index and pollutant levels (when available)

## Installation

1. Clone or download this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

### API Keys

You need at least one weather API key. Create a `.env` file in the project directory:

```bash
# Get your API keys from:
# - OpenWeatherMap: https://openweathermap.org/api
# - WeatherAPI: https://www.weatherapi.com/
# - Visual Crossing: https://www.visualcrossing.com/weather-api

OPENWEATHERMAP_API_KEY=your_openweathermap_key_here
WEATHERAPI_API_KEY=your_weatherapi_key_here
VISUALCROSSING_API_KEY=your_visualcrossing_key_here
```

### Register with Claude

Add to your Claude Desktop configuration (`~/.claude/mcp.json`):

```json
{
  "mcpServers": {
    "weather-server": {
      "command": "python3",
      "args": ["/path/to/weather_server_fixed.py"],
      "env": {
        "OPENWEATHERMAP_API_KEY": "your_key_here",
        "WEATHERAPI_API_KEY": "your_key_here"
      }
    }
  }
}
```

Or use environment variables from your `.env` file.

## Available Tools

### 1. `get_current_weather`
Get current weather conditions for any location.

**Parameters:**
- `location` (required): City name, ZIP code, or coordinates (e.g., "New York", "10001", "40.7128,-74.0060")
- `unit` (optional): "celsius", "fahrenheit", or "kelvin" (default: "celsius")
- `provider` (optional): "openweathermap", "weatherapi", or "visualcrossing"

**Example:**
```
get_current_weather("London", unit="celsius")
get_current_weather("Tokyo", provider="weatherapi")
```

### 2. `get_weather_forecast`
Get multi-day weather forecast.

**Parameters:**
- `location` (required): City name, ZIP code, or coordinates
- `days` (optional): Number of forecast days (1-10, default: 3)
- `unit` (optional): "celsius" or "fahrenheit" (default: "celsius")

**Example:**
```
get_weather_forecast("Paris", days=5, unit="celsius")
```

### 3. `search_weather_locations`
Search for locations by name.

**Parameters:**
- `query` (required): Location name to search for
- `limit` (optional): Maximum number of results (1-10, default: 5)

**Example:**
```
search_weather_locations("San", limit=3)
```

### 4. `get_available_providers`
List configured weather providers.

**Example:**
```
get_available_providers()
```

### 5. `clear_weather_cache`
Clear the weather data cache.

**Example:**
```
clear_weather_cache()
```

## Usage Examples

### With Claude Desktop
Once registered, you can ask Claude:
- "What's the weather in Tokyo?"
- "Get a 5-day forecast for London in Fahrenheit"
- "Search for locations named 'Springfield'"
- "What weather providers are available?"

### Direct Testing
You can test the server directly:

```bash
# Start the server
python3 weather_server_fixed.py

# In another terminal, test with curl or MCP inspector
```

## Provider Comparison

| Feature | OpenWeatherMap | WeatherAPI | Visual Crossing |
|---------|---------------|------------|----------------|
| Current Weather | ✅ | ✅ | ✅ |
| Forecast | ✅ (5 days free) | ✅ (10 days) | ✅ (15 days) |
| Air Quality | ✅ (separate API) | ✅ | ❌ |
| Historical Data | ✅ (paid) | ✅ (paid) | ✅ (paid) |
| Free Tier | 60 calls/min | 1M calls/month | 1000 calls/day |

## Error Handling

The server includes comprehensive error handling:
- Invalid locations return descriptive errors
- Missing API keys are detected at startup
- Network timeouts are handled gracefully
- Provider fallback if one service fails

## Development

### Adding New Providers

1. Add provider to `WeatherProvider` enum
2. Add configuration loading in `_load_configs()`
3. Implement `_get_{provider}_current()` method
4. Add provider to provider selection logic

### Testing

```bash
# Test with MCP Inspector
npx @anthropics/mcp-inspector python3 weather_server.py
```

## License

MIT License

## Contributing

Feel free to submit issues and pull requests for new features or bug fixes.