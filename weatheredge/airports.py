"""Canonical WeatherEdge airport/market registry.

Market slugs are generated from the verified Polymarket city name. Settlement
source details are recorded here so the trading pipeline never silently
substitutes a nearby observation for the settlement station.
"""

AIRPORTS = [
    {"icao": "FACT", "city": "Cape Town", "market_city": "cape-town", "country": "ZA", "tz": "Africa/Johannesburg", "lat": -33.97403, "lon": 18.60433},
    {"icao": "SAEZ", "city": "Buenos Aires", "market_city": "buenos-aires", "country": "AR", "tz": "America/Argentina/Buenos_Aires", "lat": -34.82222, "lon": -58.53583},
    {"icao": "LEMD", "city": "Madrid", "market_city": "madrid", "country": "ES", "tz": "Europe/Madrid", "lat": 40.47222, "lon": -3.56083},
    {"icao": "KATL", "city": "Atlanta", "market_city": "atlanta", "country": "US", "tz": "America/New_York", "lat": 33.64073, "lon": -84.42774},
    {"icao": "KSFO", "city": "San Francisco", "market_city": "san-francisco", "country": "US", "tz": "America/Los_Angeles", "lat": 37.62131, "lon": -122.37896},
    {"icao": "KSEA", "city": "Seattle", "market_city": "seattle", "country": "US", "tz": "America/Los_Angeles", "lat": 47.45025, "lon": -122.30882},
    {"icao": "EGLC", "city": "London", "market_city": "london", "country": "GB", "tz": "Europe/London", "lat": 51.50528, "lon": 0.05528},
    {"icao": "KBKF", "city": "Buckley", "market_city": "denver", "country": "US", "tz": "America/Denver", "lat": 39.70167, "lon": -104.75167},
    {"icao": "RJTT", "city": "Tokyo", "market_city": "tokyo", "country": "JP", "tz": "Asia/Tokyo", "lat": 35.54939, "lon": 139.77984},
]

AIRPORT_BY_ICAO = {a["icao"]: a for a in AIRPORTS}
