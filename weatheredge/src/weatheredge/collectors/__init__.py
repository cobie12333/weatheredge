"""Collectors package for WeatherEdge.

Only collectors that actually exist in this repository are exported here.
The multi-airport collectors live in the legacy-compatible top-level
scripts until the code tree is deliberately consolidated.
"""

from weatheredge.collectors.metar import MetarCollector
from weatheredge.collectors.saws import SawsCollector
from weatheredge.collectors.pws import PwsCollector

__all__ = ["MetarCollector", "SawsCollector", "PwsCollector"]
