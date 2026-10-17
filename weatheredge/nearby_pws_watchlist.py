"""Nearby Weather Underground PWS watchlist transcribed from Nearby PWS.docx.

This is a discovery/watchlist only. Coordinates, distances, current online status,
and API availability have NOT been independently verified. Do not enable these
stations for live collection until their metadata/feed is verified.
"""

AIRPORTS = {
    "EHAM": ("Amsterdam", ["IAMSTE373", "INOORDHO84", "IAALSMEE38", "IHOOFD93"]),
    "SAEZ": ("Buenos Aires", ["IEZEIZ1", "IEZEIZ7", "IMONTEGR27"]),
    "HKK": ("Hong Kong", ["IKOWLO16", "IHONGKON111", "IYAUTS4", "IHONGK71"]),
    "OPKC": ("Karachi", ["IKARAC79", "IKARAC25", "IKARAC41"]),
    "EGLC": ("London", ["IBARKI7", "ILONDO575", "ILONDO672", "ILONDON828"]),
    "LEMD": ("Madrid", ["IPARAC71", "IMADRI265", "IMADRI56", "IMADRI204"]),
    "RPLL": ("Manila", ["IPASAY7", "IPARAAQU3", "ILASPI24", "ITAGUI1"]),
    "MMMX": ("Mexico City", ["INEZAH1", "IMEXIC225", "IMEXIC275", "IMEXIC197"]),
    "LIMC": ("Milan", ["ILONAT3", "ILOMBARD227", "ISAMAR22", "IGALLA20"]),
    "EDDM": ("Munich", ["IOBFREIS10", "IFREIS66", "IOBERD38", "IFREIS64", "IMARZL1"]),
    "MPMG": ("Panama", ["IPANAM90", "IPANAM95", "IPANAM105"]),
    "LFPB": ("Paris", ["ICOUEN15", "ILESPA16", "IROISS4", "IDRANC6"]),
    "WSSS": ("Singapore", ["ISINGA249", "ISINGA263", "ISINGA128", "ISINGA64"]),
    "RCSS": ("Taipei", ["ITAIPE50", "IDATON1", "ITAIPE29"]),
    "LLBG": ("Tel Aviv", ["IMKEFARG2", "IRAMAT31", "IGANEI2"]),
    "CYYZ": ("Toronto", ["ITORON175", "ITORON111", "IETOBI26", "IBRAMP64"]),
    "EPWA": ("Warsaw", ["IWARSAW116", "IRYBIE3", "IWARSA530", "IRASZY1"]),
    "FACT": ("Cape Town", ["IMATRO5"]),
}

PWS_WATCHLIST = [
    {
        "station_id": station_id,
        "airport_icao": airport_icao,
        "city": city,
        "source": "weatherunderground",
        "source_url": f"https://www.wunderground.com/dashboard/pws/{station_id}",
        "metadata_verified": False,
        "enabled": False,
    }
    for airport_icao, (city, station_ids) in AIRPORTS.items()
    for station_id in station_ids
]


def stations_for_airport(airport_icao):
    """Return watchlist entries for an airport code (empty list if unknown)."""
    code = airport_icao.upper()
    return [station.copy() for station in PWS_WATCHLIST
            if station["airport_icao"] == code]
