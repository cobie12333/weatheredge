"""Configured Polymarket weather airport watchlist.

Add a station here when its settlement rules and observation source have been
verified. This is configuration, not a claim that every market is profitable.
"""

AIRPORTS = [
    {"icao": "FACT", "city": "Cape Town", "country": "ZA", "tz": "Africa/Johannesburg"},
    {"icao": "SAEZ", "city": "Buenos Aires", "country": "AR", "tz": "America/Argentina/Buenos_Aires"},
    {"icao": "LEMD", "city": "Madrid", "country": "ES", "tz": "Europe/Madrid"},
    {"icao": "KATL", "city": "Atlanta", "country": "US", "tz": "America/New_York"},
    {"icao": "KSFO", "city": "San Francisco", "country": "US", "tz": "America/Los_Angeles"},
    {"icao": "KSEA", "city": "Seattle", "country": "US", "tz": "America/Los_Angeles"},
    {"icao": "EGLC", "city": "London City", "country": "GB", "tz": "Europe/London"},
    {"icao": "KBKF", "city": "Buckley", "country": "US", "tz": "America/Denver"},
    {"icao": "RJTT", "city": "Tokyo Haneda", "country": "JP", "tz": "Asia/Tokyo"},
]

AIRPORT_BY_ICAO = {a["icao"]: a for a in AIRPORTS}
