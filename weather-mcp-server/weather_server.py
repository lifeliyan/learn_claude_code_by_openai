#!/usr/bin/env python3
"""
weather_server.py - Weather Integration MCP Server

A comprehensive weather MCP server that provides multiple weather services:
1. Current weather conditions
2. Weather forecasts
3. Historical weather data
4. Air quality information
5. Multiple provider support (OpenWeatherMap, WeatherAPI, etc.)

Features:
- Caching for rate limiting
- Fallback providers
- Unit conversion
- Location search
- Error handling
"""

import os
import json
import asyncio
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================================================
# Configuration and Constants
# ============================================================

class WeatherProvider(Enum):
    """Supported weather providers"""
    OPENWEATHERMAP = "openweathermap"
    WEATHERAPI = "weatherapi"
    VISUALCROSSING = "visualcrossing"

@dataclass
class WeatherConfig:
    """Weather service configuration"""
    provider: WeatherProvider
    api_key: str
    base_url: str
    cache_ttl: int = 300  # 5 minutes cache

class TemperatureUnit(Enum):
    CELSIUS = "celsius"
    FAHRENHEIT = "fahrenheit"
    KELVIN = "kelvin"

# ============================================================
# Cache Implementation
# ============================================================

class WeatherCache:
    """Simple in-memory cache for weather data"""
    
    def __init__(self):
        self._cache: Dict[str, tuple[Any, datetime]] = {}
    
    def get(self, key: str) -> Optional[Any]:
        """Get cached value if not expired"""
        if key in self._cache:
            value, timestamp = self._cache[key]
            if datetime.now() - timestamp < timedelta(seconds=300):  # 5 minutes
                return value
            else:
                del self._cache[key]
        return None
    
    def set(self, key: str, value: Any):
        """Cache a value"""
        self._cache[key] = (value, datetime.now())
    
    def clear(self):
        """Clear all cache"""
        self._cache.clear()

# ============================================================
# Weather Service Implementation
# ============================================================

class WeatherService:
    """Main weather service with multiple provider support"""
    
    def __init__(self):
        self.cache = WeatherCache()
        try:
            self.configs = self._load_configs()
        except Exception as e:
            raise RuntimeError(f"Failed to load weather configs: {e}") from e
        
        # Save and clear ALL proxy-related environment variables
        # This is the most reliable way to avoid httpx proxy parsing issues
        proxy_vars_to_clear = [
            'http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY',
            'all_proxy', 'ALL_PROXY', 'no_proxy', 'NO_PROXY',
            'ftp_proxy', 'FTP_PROXY', 'socks_proxy', 'SOCKS_PROXY'
        ]
        
        saved_proxies = {}
        for var in proxy_vars_to_clear:
            if var in os.environ:
                saved_proxies[var] = os.environ[var]
                del os.environ[var]
        
        try:
            # Create client - trust_env should be irrelevant now since env vars are cleared
            self.client = httpx.AsyncClient(
                proxy=None,
                mounts={
                    "http://": None,
                    "https://": None,
                    "all://": None
                },
                trust_env=False
            )
        except Exception as e:
            # Restore environment variables before re-raising
            for var, value in saved_proxies.items():
                os.environ[var] = value
            raise RuntimeError(f"Failed to create httpx client: {e}") from e
        
        # Restore environment variables
        for var, value in saved_proxies.items():
            os.environ[var] = value
    
    def _load_configs(self) -> Dict[WeatherProvider, WeatherConfig]:
        """Load configuration from environment variables"""
        configs = {}
        
        # OpenWeatherMap
        owm_key = os.getenv("OPENWEATHERMAP_API_KEY")
        if owm_key:
            configs[WeatherProvider.OPENWEATHERMAP] = WeatherConfig(
                provider=WeatherProvider.OPENWEATHERMAP,
                api_key=owm_key,
                base_url="https://api.openweathermap.org/data/2.5"
            )
        
        # WeatherAPI
        wa_key = os.getenv("WEATHERAPI_API_KEY")
        if wa_key:
            configs[WeatherProvider.WEATHERAPI] = WeatherConfig(
                provider=WeatherProvider.WEATHERAPI,
                api_key=wa_key,
                base_url="http://api.weatherapi.com/v1"
            )
        
        # Visual Crossing
        vc_key = os.getenv("VISUALCROSSING_API_KEY")
        if vc_key:
            configs[WeatherProvider.VISUALCROSSING] = WeatherConfig(
                provider=WeatherProvider.VISUALCROSSING,
                api_key=vc_key,
                base_url="https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services"
            )
        
        if not configs:
            raise ValueError("No weather API keys found in environment variables")
        
        return configs
    
    def _generate_cache_key(self, provider: WeatherProvider, endpoint: str, params: Dict) -> str:
        """Generate a cache key for weather requests"""
        key_data = f"{provider.value}:{endpoint}:{json.dumps(params, sort_keys=True)}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    async def get_current_weather(
        self, 
        location: str, 
        unit: TemperatureUnit = TemperatureUnit.CELSIUS,
        provider: Optional[WeatherProvider] = None
    ) -> Dict[str, Any]:
        """Get current weather for a location"""
        
        # Try providers in order
        providers_to_try = []
        if provider:
            providers_to_try = [provider]
        else:
            # Default order: WeatherAPI, OpenWeatherMap, VisualCrossing
            providers_to_try = [
                WeatherProvider.WEATHERAPI,
                WeatherProvider.OPENWEATHERMAP,
                WeatherProvider.VISUALCROSSING
            ]
        
        last_error = None
        for provider_choice in providers_to_try:
            if provider_choice not in self.configs:
                continue
            
            try:
                if provider_choice == WeatherProvider.OPENWEATHERMAP:
                    return await self._get_openweathermap_current(location, unit)
                elif provider_choice == WeatherProvider.WEATHERAPI:
                    return await self._get_weatherapi_current(location, unit)
                elif provider_choice == WeatherProvider.VISUALCROSSING:
                    return await self._get_visualcrossing_current(location, unit)
            except Exception as e:
                last_error = e
                continue
        
        raise Exception(f"All weather providers failed. Last error: {last_error}")
    
    async def _get_openweathermap_current(self, location: str, unit: TemperatureUnit) -> Dict[str, Any]:
        """Get current weather from OpenWeatherMap"""
        config = self.configs[WeatherProvider.OPENWEATHERMAP]
        
        # First, get coordinates for the location
        geocode_params = {
            "q": location,
            "limit": 1,
            "appid": config.api_key
        }
        
        geocode_response = await self.client.get(
            f"http://api.openweathermap.org/geo/1.0/direct",
            params=geocode_params
        )
        geocode_response.raise_for_status()
        geocode_data = geocode_response.json()
        
        if not geocode_data:
            raise ValueError(f"Location '{location}' not found")
        
        lat = geocode_data[0]["lat"]
        lon = geocode_data[0]["lon"]
        city_name = geocode_data[0].get("name", location)
        
        # Get weather data
        cache_key = self._generate_cache_key(
            WeatherProvider.OPENWEATHERMAP,
            "weather",
            {"lat": lat, "lon": lon, "unit": unit.value}
        )
        
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        # Determine units for OpenWeatherMap
        if unit == TemperatureUnit.FAHRENHEIT:
            units_param = "imperial"
        elif unit == TemperatureUnit.CELSIUS:
            units_param = "metric"
        else:
            units_param = "standard"  # Kelvin
        
        weather_params = {
            "lat": lat,
            "lon": lon,
            "appid": config.api_key,
            "units": units_param
        }
        
        weather_response = await self.client.get(
            f"{config.base_url}/weather",
            params=weather_params
        )
        weather_response.raise_for_status()
        weather_data = weather_response.json()
        
        # Format response
        result = {
            "location": city_name,
            "temperature": weather_data["main"]["temp"],
            "feels_like": weather_data["main"]["feels_like"],
            "humidity": weather_data["main"]["humidity"],
            "pressure": weather_data["main"]["pressure"],
            "weather": weather_data["weather"][0]["description"],
            "wind_speed": weather_data["wind"]["speed"],
            "wind_direction": weather_data["wind"].get("deg", 0),
            "cloudiness": weather_data["clouds"]["all"],
            "visibility": weather_data.get("visibility", 10000),
            "sunrise": datetime.fromtimestamp(weather_data["sys"]["sunrise"]).isoformat(),
            "sunset": datetime.fromtimestamp(weather_data["sys"]["sunset"]).isoformat(),
            "unit": unit.value,
            "provider": "OpenWeatherMap",
            "timestamp": datetime.now().isoformat()
        }
        
        self.cache.set(cache_key, result)
        return result
    
    async def _get_weatherapi_current(self, location: str, unit: TemperatureUnit) -> Dict[str, Any]:
        """Get current weather from WeatherAPI"""
        config = self.configs[WeatherProvider.WEATHERAPI]
        
        cache_key = self._generate_cache_key(
            WeatherProvider.WEATHERAPI,
            "current",
            {"q": location, "unit": unit.value}
        )
        
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        # WeatherAPI uses different parameter names
        if unit == TemperatureUnit.FAHRENHEIT:
            temp_unit = "f"
        else:
            temp_unit = "c"
        
        params = {
            "key": config.api_key,
            "q": location,
            "aqi": "yes"  # Include air quality
        }
        
        response = await self.client.get(
            f"{config.base_url}/current.json",
            params=params
        )
        response.raise_for_status()
        data = response.json()
        
        # Format response
        result = {
            "location": f"{data['location']['name']}, {data['location']['country']}",
            "temperature": data["current"][f"temp_{temp_unit}"],
            "feels_like": data["current"][f"feelslike_{temp_unit}"],
            "humidity": data["current"]["humidity"],
            "pressure": data["current"]["pressure_mb"],
            "weather": data["current"]["condition"]["text"],
            "wind_speed": data["current"][f"wind_{'mph' if temp_unit == 'f' else 'kph'}"],
            "wind_direction": data["current"]["wind_degree"],
            "cloudiness": data["current"]["cloud"],
            "visibility": data["current"][f"vis_{'miles' if temp_unit == 'f' else 'km'}"],
            "uv_index": data["current"]["uv"],
            "air_quality": data["current"].get("air_quality", {}),
            "unit": unit.value,
            "provider": "WeatherAPI",
            "timestamp": datetime.now().isoformat()
        }
        
        self.cache.set(cache_key, result)
        return result
    
    async def _get_visualcrossing_current(self, location: str, unit: TemperatureUnit) -> Dict[str, Any]:
        """Get current weather from Visual Crossing"""
        config = self.configs[WeatherProvider.VISUALCROSSING]
        
        cache_key = self._generate_cache_key(
            WeatherProvider.VISUALCROSSING,
            "current",
            {"location": location, "unit": unit.value}
        )
        
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        # Visual Crossing uses different units
        if unit == TemperatureUnit.FAHRENHEIT:
            unit_param = "us"
        else:
            unit_param = "metric"
        
        params = {
            "key": config.api_key,
            "unitGroup": unit_param,
            "contentType": "json",
            "include": "current"
        }
        
        response = await self.client.get(
            f"{config.base_url}/timeline/{location}/today",
            params=params
        )
        response.raise_for_status()
        data = response.json()
        
        current = data["days"][0]
        
        result = {
            "location": data["resolvedAddress"],
            "temperature": current["temp"],
            "feels_like": current["feelslike"],
            "humidity": current["humidity"],
            "pressure": current["pressure"],
            "weather": current["conditions"],
            "wind_speed": current["windspeed"],
            "wind_direction": current["winddir"],
            "cloudiness": current["cloudcover"],
            "visibility": current["visibility"],
            "uv_index": current["uvindex"],
            "precipitation": current["precip"],
            "snow": current.get("snow", 0),
            "sunrise": current["sunrise"],
            "sunset": current["sunset"],
            "unit": unit.value,
            "provider": "VisualCrossing",
            "timestamp": datetime.now().isoformat()
        }
        
        self.cache.set(cache_key, result)
        return result
    
    async def get_forecast(
        self, 
        location: str, 
        days: int = 3,
        unit: TemperatureUnit = TemperatureUnit.CELSIUS
    ) -> Dict[str, Any]:
        """Get weather forecast for a location"""
        
        # Use WeatherAPI for forecasts if available
        if WeatherProvider.WEATHERAPI in self.configs:
            return await self._get_weatherapi_forecast(location, days, unit)
        elif WeatherProvider.OPENWEATHERMAP in self.configs:
            return await self._get_openweathermap_forecast(location, days, unit)
        else:
            raise Exception("No forecast provider available")
    
    async def _get_weatherapi_forecast(self, location: str, days: int, unit: TemperatureUnit) -> Dict[str, Any]:
        """Get forecast from WeatherAPI"""
        config = self.configs[WeatherProvider.WEATHERAPI]
        
        cache_key = self._generate_cache_key(
            WeatherProvider.WEATHERAPI,
            "forecast",
            {"q": location, "days": days, "unit": unit.value}
        )
        
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        if unit == TemperatureUnit.FAHRENHEIT:
            temp_unit = "f"
        else:
            temp_unit = "c"
        
        params = {
            "key": config.api_key,
            "q": location,
            "days": min(days, 10),  # WeatherAPI max 10 days
            "aqi": "yes",
            "alerts": "yes"
        }
        
        response = await self.client.get(
            f"{config.base_url}/forecast.json",
            params=params
        )
        response.raise_for_status()
        data = response.json()
        
        forecast_days = []
        for day in data["forecast"]["forecastday"]:
            forecast_days.append({
                "date": day["date"],
                "max_temp": day["day"][f"maxtemp_{temp_unit}"],
                "min_temp": day["day"][f"mintemp_{temp_unit}"],
                "avg_temp": day["day"][f"avgtemp_{temp_unit}"],
                "condition": day["day"]["condition"]["text"],
                "max_wind": day["day"][f"maxwind_{'mph' if temp_unit == 'f' else 'kph'}"],
                "total_precip": day["day"]["totalprecip_mm"],
                "chance_of_rain": day["day"]["daily_chance_of_rain"],
                "chance_of_snow": day["day"]["daily_chance_of_snow"],
                "uv_index": day["day"]["uv"],
                "sunrise": day["astro"]["sunrise"],
                "sunset": day["astro"]["sunset"]
            })
        
        result = {
            "location": f"{data['location']['name']}, {data['location']['country']}",
            "forecast_days": forecast_days,
            "unit": unit.value,
            "provider": "WeatherAPI",
            "timestamp": datetime.now().isoformat()
        }
        
        self.cache.set(cache_key, result)
        return result
    
    async def search_locations(self, query: str, limit: int = 5) -> List[Dict[str, str]]:
        """Search for locations by name"""
        if WeatherProvider.WEATHERAPI in self.configs:
            return await self._search_weatherapi_locations(query, limit)
        else:
            return await self._search_openweathermap_locations(query, limit)
    
    async def _search_weatherapi_locations(self, query: str, limit: int) -> List[Dict[str, str]]:
        """Search locations using WeatherAPI"""
        config = self.configs[WeatherProvider.WEATHERAPI]
        
        params = {
            "key": config.api_key,
            "q": query
        }
        
        response = await self.client.get(
            f"{config.base_url}/search.json",
            params=params
        )
        response.raise_for_status()
        data = response.json()
        
        locations = []
        for loc in data[:limit]:
            locations.append({
                "name": f"{loc['name']}, {loc['region']}, {loc['country']}",
                "lat": loc["lat"],
                "lon": loc["lon"]
            })
        
        return locations
    
    async def _search_openweathermap_locations(self, query: str, limit: int) -> List[Dict[str, str]]:
        """Search locations using OpenWeatherMap"""
        config = self.configs[WeatherProvider.OPENWEATHERMAP]
        
        params = {
            "q": query,
            "limit": limit,
            "appid": config.api_key
        }
        
        response = await self.client.get(
            "http://api.openweathermap.org/geo/1.0/direct",
            params=params
        )
        response.raise_for_status()
        data = response.json()
        
        locations = []
        for loc in data:
            locations.append({
                "name": f"{loc.get('name', '')}, {loc.get('state', '')}, {loc.get('country', '')}",
                "lat": loc["lat"],
                "lon": loc["lon"]
            })
        
        return locations
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()

# ============================================================
# MCP Server Implementation
# ============================================================

# Create server instance
server = Server("weather-server")

# Initialize weather service (lazy initialization)
weather_service = None

def get_weather_service():
    """Get or create the weather service instance"""
    global weather_service
    if weather_service is None:
        weather_service = WeatherService()
    return weather_service

@server.tool()
async def get_current_weather(
    location: str,
    unit: str = "celsius",
    provider: Optional[str] = None
) -> str:
    """Get current weather conditions for a location.

    Args:
        location: City name, ZIP code, or coordinates (e.g., "New York", "10001", "40.7128,-74.0060")
        unit: Temperature unit - "celsius", "fahrenheit", or "kelvin" (default: "celsius")
        provider: Weather provider - "openweathermap", "weatherapi", or "visualcrossing" (optional)
    """
    try:
        # Validate unit
        try:
            temp_unit = TemperatureUnit(unit.lower())
        except ValueError:
            return f"Error: Invalid unit '{unit}'. Use 'celsius', 'fahrenheit', or 'kelvin'."
        
        # Validate provider if specified
        weather_provider = None
        if provider:
            try:
                weather_provider = WeatherProvider(provider.lower())
            except ValueError:
                return f"Error: Invalid provider '{provider}'. Use 'openweathermap', 'weatherapi', or 'visualcrossing'."
        
        # Get weather data
        weather_data = await get_weather_service().get_current_weather(
            location, 
            temp_unit, 
            weather_provider
        )
        
        # Format response
        response = f"🌤️ **Current Weather for {weather_data['location']}**\n\n"
        response += f"**Temperature**: {weather_data['temperature']}°{temp_unit.value[0].upper()}\n"
        response += f"**Feels Like**: {weather_data['feels_like']}°{temp_unit.value[0].upper()}\n"
        response += f"**Conditions**: {weather_data['weather'].title()}\n"
        response += f"**Humidity**: {weather_data['humidity']}%\n"
        wind_unit = 'mph' if temp_unit == TemperatureUnit.FAHRENHEIT else 'km/h'
        response += f"**Wind**: {weather_data['wind_speed']} {wind_unit} from {weather_data['wind_direction']}°\n"
        response += f"**Pressure**: {weather_data['pressure']} hPa\n"
        visibility_unit = 'miles' if temp_unit == TemperatureUnit.FAHRENHEIT else 'km'
        response += f"**Visibility**: {weather_data['visibility']} {visibility_unit}\n"
        response += f"**Cloudiness**: {weather_data['cloudiness']}%\n\n"
        response += f"**Additional Info:**\n"
        response += f"- Sunrise: {weather_data.get('sunrise', 'N/A')}\n"
        response += f"- Sunset: {weather_data.get('sunset', 'N/A')}\n"
        response += f"- UV Index: {weather_data.get('uv_index', 'N/A')}\n"
        response += f"- Provider: {weather_data['provider']}\n"
        response += f"- Updated: {weather_data['timestamp']}"

        if 'air_quality' in weather_data and weather_data['air_quality']:
            aq = weather_data['air_quality']
            response += "\n\n**Air Quality:**\n"
            response += f"- PM2.5: {aq.get('pm2_5', 'N/A')}\n"
            response += f"- PM10: {aq.get('pm10', 'N/A')}\n"
            response += f"- O3: {aq.get('o3', 'N/A')}\n"
            response += f"- NO2: {aq.get('no2', 'N/A')}\n"
            response += f"- SO2: {aq.get('so2', 'N/A')}\n"
            response += f"- CO: {aq.get('co', 'N/A')}\n"

        return response
        
    except Exception as e:
        return f"Error getting weather: {str(e)}"

@server.tool()
async def get_weather_forecast(
    location: str,
    days: int = 3,
    unit: str = "celsius"
) -> str:
    """Get weather forecast for a location.

    Args:
        location: City name, ZIP code, or coordinates
        days: Number of forecast days (1-10, default: 3)
        unit: Temperature unit - "celsius" or "fahrenheit" (default: "celsius")
    """
    try:
        # Validate days
        if days < 1 or days > 10:
            return "Error: Days must be between 1 and 10"
        
        # Validate unit
        try:
            temp_unit = TemperatureUnit(unit.lower())
            if temp_unit == TemperatureUnit.KELVIN:
                return "Error: Kelvin not supported for forecasts. Use 'celsius' or 'fahrenheit'."
        except ValueError:
            return f"Error: Invalid unit '{unit}'. Use 'celsius' or 'fahrenheit'."
        
        # Get forecast
        forecast_data = await get_weather_service().get_forecast(location, days, temp_unit)
        
        # Format response
        response = f"📅 **{days}-Day Forecast for {forecast_data['location']}**\n\n"
        
        for i, day in enumerate(forecast_data['forecast_days']):
            temp_symbol = "°F" if temp_unit == TemperatureUnit.FAHRENHEIT else "°C"
            response += f"**Day {i+1} ({day['date']}):**\n"
            response += f"  🌡️  High: {day['max_temp']}{temp_symbol} | Low: {day['min_temp']}{temp_symbol}\n"
            response += f"  ☁️  {day['condition']}\n"
            forecast_wind_unit = 'mph' if temp_unit == TemperatureUnit.FAHRENHEIT else 'km/h'
            response += f"  💨  Max Wind: {day['max_wind']} {forecast_wind_unit}\n"
            response += f"  🌧️  Rain Chance: {day['chance_of_rain']}% | Precipitation: {day['total_precip']} mm\n"
            response += f"  ❄️  Snow Chance: {day['chance_of_snow']}%\n"
            response += f"  ☀️  UV Index: {day['uv_index']}\n"
            response += f"  🌅  Sunrise: {day['sunrise']} | Sunset: {day['sunset']}\n\n"
        
        response += f"\n*Provider: {forecast_data['provider']} | Updated: {forecast_data['timestamp']}*"
        
        return response
        
    except Exception as e:
        return f"Error getting forecast: {str(e)}"

@server.tool()
async def search_weather_locations(
    query: str,
    limit: int = 5
) -> str:
    """Search for locations by name.

    Args:
        query: Location name to search for
        limit: Maximum number of results (1-10, default: 5)
    """
    try:
        if limit < 1 or limit > 10:
            return "Error: Limit must be between 1 and 10"
        
        locations = await get_weather_service().search_locations(query, limit)
        
        if not locations:
            return f"No locations found for '{query}'"
        
        response = f"📍 **Search Results for '{query}':**\n\n"
        
        for i, loc in enumerate(locations, 1):
            response += f"{i}. {loc['name']} (Lat: {loc['lat']}, Lon: {loc['lon']})\n"
        
        response += f"\n*Found {len(locations)} location(s)*"
        
        return response
        
    except Exception as e:
        return f"Error searching locations: {str(e)}"

@server.tool()
async def get_available_providers() -> str:
    """Get list of available weather providers."""
    providers = []
    
    if os.getenv("OPENWEATHERMAP_API_KEY"):
        providers.append("OpenWeatherMap")
    
    if os.getenv("WEATHERAPI_API_KEY"):
        providers.append("WeatherAPI")
    
    if os.getenv("VISUALCROSSING_API_KEY"):
        providers.append("VisualCrossing")
    
    if not providers:
        return "No weather providers configured. Please set API keys in environment variables."
    
    return f"**Available Weather Providers:**\n\n" + "\n".join(f"• {p}" for p in providers)

@server.tool()
async def clear_weather_cache() -> str:
    """Clear the weather data cache."""
    get_weather_service().cache.clear()
    return "✅ Weather cache cleared successfully."

# ============================================================
# Main Server Execution
# ============================================================

async def main():
    """Run the MCP server"""
    print("Starting Weather MCP Server...", file=sys.stderr)
    print(f"Available providers: {list(get_weather_service().configs.keys())}", file=sys.stderr)
    
    async with stdio_server() as (read, write):
        await server.run(read, write)

if __name__ == "__main__":
    import sys
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nWeather server shutting down...", file=sys.stderr)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Clean up
        try:
            if weather_service is not None:
                asyncio.run(weather_service.close())
        except:
            pass