"""Verified/identified PWS registry.

These are research inputs, not settlement stations. A PWS is only enabled for
collection after its feed is independently verified. 'verified' means the
station identity/location was verified from its provider page; it does not
mean the station is currently online or predictive.
"""

PWS_STATIONS = [
    {"station_id":"IMATRO4","airport_icao":"FACT","name":"Cape Town International Airport","source":"weatherunderground","source_url":"https://www.wunderground.com/dashboard/pws/IMATRO4","lat":-33.975,"lon":18.605,"distance_km":0.12,"status":"offline","verified":1,"enabled":0,"notes":"Provider page identifies it as Cape Town International Airport; currently offline."},
    {"station_id":"IMATRO5","airport_icao":"FACT","name":"Cape Town International Airport","source":"weatherunderground","source_url":"https://www.wunderground.com/dashboard/pws/IMATRO5","lat":-33.97,"lon":18.59,"distance_km":1.40,"status":"offline","verified":1,"enabled":0,"notes":"Historical FACT-area PWS candidate; currently offline."},
    {"station_id":"IBELLV58","airport_icao":"FACT","name":"Bellville 1","source":"weatherunderground","source_url":"https://www.wunderground.com/dashboard/pws/IBELLV58","lat":-33.90,"lon":18.61,"distance_km":8.25,"status":"offline","verified":1,"enabled":0,"notes":"Bellville station; useful as a comparison candidate, not a settlement sensor."},
    {"station_id":"IEZEIZ1","airport_icao":"SAEZ","name":"Daza - Ezeiza","source":"weatherunderground","source_url":"https://www.wunderground.com/dashboard/pws/IEZEIZ1","lat":-34.85,"lon":-58.51,"distance_km":3.89,"status":"offline","verified":1,"enabled":0,"notes":"Ezeiza-area PWS with historical data; currently offline."},
    {"station_id":"IMADRID333","airport_icao":"LEMD","name":"Madrid-Cruz del Rayo","source":"weatherunderground","source_url":"https://www.wunderground.com/dashboard/pws/IMADRID333","lat":40.44,"lon":-3.68,"distance_km":10.70,"status":"offline","verified":1,"enabled":0,"notes":"Madrid PWS candidate; distance makes it a comparison input, not an airport proxy."},
    {"station_id":"KWASEATT2649","airport_icao":"KSEA","name":"Downtown","source":"weatherunderground","source_url":"https://www.wunderground.com/dashboard/pws/KWASEATT2649","lat":47.58,"lon":-122.38,"distance_km":15.39,"status":"offline","verified":1,"enabled":0,"notes":"Seattle PWS candidate; currently offline."},
    {"station_id":"ILONDON1479","airport_icao":"EGLC","name":"London City Airport","source":"weatherunderground","source_url":"https://www.wunderground.com/dashboard/pws/ILONDON1479","lat":51.51,"lon":0.04,"distance_km":1.18,"status":"offline","verified":1,"enabled":0,"notes":"Provider page identifies it as London City Airport; currently offline."},
    {"station_id":"KCOAUROR70","airport_icao":"KBKF","name":"Buckley & Mississippi Tollgate","source":"weatherunderground","source_url":"https://www.wunderground.com/dashboard/pws/KCOAUROR70","lat":39.70,"lon":-104.78,"distance_km":2.43,"status":"offline","verified":1,"enabled":0,"notes":"Buckley/Aurora comparison station; currently offline."},
    {"station_id":"KCOCOMME17","airport_icao":"KBKF","name":"Buckley Ranch","source":"weatherunderground","source_url":"https://www.wunderground.com/dashboard/pws/KCOCOMME17","lat":39.89,"lon":-104.79,"distance_km":21.20,"status":"offline","verified":1,"enabled":0,"notes":"Buckley-area comparison station; farther away and currently offline."},
]

PWS_BY_AIRPORT = {}
for station in PWS_STATIONS:
    PWS_BY_AIRPORT.setdefault(station["airport_icao"], []).append(station)
