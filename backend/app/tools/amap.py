"""Amap (高德地图) API tools for navigator agent.

This module provides LangChain tools for interacting with Amap API:
- amap_geocode: Convert address to coordinates
- amap_place_search: Search POI by keywords
- amap_place_around: Search POI around a location
- amap_driving_route: Plan driving route
"""

import httpx
from langchain_core.tools import tool
from typing import Optional

from app.core.config import settings


# Amap API base URL
AMAP_BASE_URL = "https://restapi.amap.com"


def get_amap_key() -> str:
    """Get Amap API key from settings.
    
    Raises:
        ValueError: If AMAP_KEY is not configured
    """
    if settings.AMAP_KEY is None:
        raise ValueError("AMAP_KEY is not configured. Please set it in your .env file.")
    return settings.AMAP_KEY.get_secret_value()


@tool
async def amap_geocode(address: str, city: Optional[str] = None) -> str:
    """Convert structured address to longitude/latitude coordinates (geocoding).
    
    Used to convert Chinese addresses to Amap coordinates. Supports landmark names.
    
    Args:
        address: Structured address, e.g., "北京市朝阳区阜通东大街6号" or "天安门"
        city: Optional, specify query city, can be city name, citycode or adcode
    
    Returns:
        JSON string containing coordinates and address information
    """
    key = get_amap_key()
    
    params = {
        "key": key,
        "address": address,
        "output": "JSON",
    }
    
    if city:
        params["city"] = city
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{AMAP_BASE_URL}/v3/geocode/geo",
            params=params,
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
    
    if data.get("status") != "1":
        return f"Geocoding failed: {data.get('info', 'Unknown error')}"
    
    geocodes = data.get("geocodes", [])
    if not geocodes:
        return f"No coordinates found for address '{address}'"
    
    # Format results
    results = []
    for geo in geocodes:
        results.append({
            "formatted_address": geo.get("formatted_address", ""),
            "location": geo.get("location", ""),
            "province": geo.get("province", ""),
            "city": geo.get("city", ""),
            "district": geo.get("district", ""),
            "level": geo.get("level", ""),
        })
    
    import json
    return json.dumps(results, ensure_ascii=False, indent=2)


@tool
async def amap_place_search(
    keywords: str,
    city: Optional[str] = None,
    citylimit: bool = False,
    types: Optional[str] = None,
    offset: int = 10,
    page: int = 1,
) -> str:
    """Search POI (Point of Interest) by keywords.
    
    Search for places by keywords, such as "星巴克", "火锅", "中科大", etc.
    
    Args:
        keywords: Search keywords, multiple keywords separated by "|"
        city: Optional, query city
        citylimit: Whether to return only specified city data, default False
        types: Optional, POI type code, e.g., "050301" for Chinese restaurants
        offset: Number of results per page, default 10, max 25
        page: Current page number, default 1, max 100
    
    Returns:
        JSON string containing POI list with name, address, coordinates, phone, etc.
    """
    key = get_amap_key()
    
    params = {
        "key": key,
        "keywords": keywords,
        "offset": min(offset, 25),
        "page": page,
        "extensions": "all",
        "output": "JSON",
    }
    
    if city:
        params["city"] = city
    if citylimit:
        params["citylimit"] = "true"
    if types:
        params["types"] = types
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{AMAP_BASE_URL}/v3/place/text",
            params=params,
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
    
    if data.get("status") != "1":
        return f"Search failed: {data.get('info', 'Unknown error')}"
    
    pois = data.get("pois", [])
    if not pois:
        return f"No places found for keywords '{keywords}'"
    
    # Format results
    results = []
    for poi in pois:
        results.append({
            "id": poi.get("id", ""),
            "name": poi.get("name", ""),
            "type": poi.get("type", ""),
            "typecode": poi.get("typecode", ""),
            "address": poi.get("address", ""),
            "location": poi.get("location", ""),
            "pname": poi.get("pname", ""),  # Province
            "cityname": poi.get("cityname", ""),  # City
            "adname": poi.get("adname", ""),  # District
            "tel": poi.get("tel", ""),
            "rating": poi.get("biz_ext", {}).get("rating", ""),
            "cost": poi.get("biz_ext", {}).get("cost", ""),
        })
    
    import json
    result_data = {
        "count": data.get("count", "0"),
        "pois": results,
    }
    return json.dumps(result_data, ensure_ascii=False, indent=2)


@tool
async def amap_place_around(
    location: str,
    keywords: Optional[str] = None,
    types: Optional[str] = None,
    radius: int = 3000,
    sortrule: str = "distance",
    offset: int = 10,
    page: int = 1,
) -> str:
    """Search POI around a location.
    
    Search for places around specified coordinates, results sorted by distance.
    
    Args:
        location: Center coordinates, format "longitude,latitude", e.g., "116.473168,39.993015"
        keywords: Optional, search keywords
        types: Optional, POI type code
        radius: Search radius in meters, default 3000, max 50000
        sortrule: Sort rule, "distance" for distance, "weight" for comprehensive sorting
        offset: Number of results per page, default 10, max 25
        page: Current page number, default 1
    
    Returns:
        JSON string containing nearby POI list, sorted by distance
    """
    key = get_amap_key()
    
    params = {
        "key": key,
        "location": location,
        "radius": min(radius, 50000),
        "sortrule": sortrule,
        "offset": min(offset, 25),
        "page": page,
        "extensions": "all",
        "output": "JSON",
    }
    
    if keywords:
        params["keywords"] = keywords
    if types:
        params["types"] = types
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{AMAP_BASE_URL}/v3/place/around",
            params=params,
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
    
    if data.get("status") != "1":
        return f"Nearby search failed: {data.get('info', 'Unknown error')}"
    
    pois = data.get("pois", [])
    if not pois:
        return f"No places found around coordinates {location}"
    
    # Format results
    results = []
    for poi in pois:
        results.append({
            "id": poi.get("id", ""),
            "name": poi.get("name", ""),
            "type": poi.get("type", ""),
            "address": poi.get("address", ""),
            "location": poi.get("location", ""),
            "distance": poi.get("distance", ""),  # Distance from center (meters)
            "pname": poi.get("pname", ""),
            "cityname": poi.get("cityname", ""),
            "adname": poi.get("adname", ""),
            "tel": poi.get("tel", ""),
            "rating": poi.get("biz_ext", {}).get("rating", ""),
        })
    
    import json
    result_data = {
        "center": location,
        "radius": radius,
        "count": data.get("count", "0"),
        "pois": results,
    }
    return json.dumps(result_data, ensure_ascii=False, indent=2)


@tool
async def amap_driving_route(
    origin: str,
    destination: str,
    waypoints: Optional[str] = None,
    strategy: int = 32,
    show_fields: str = "cost,tmcs,navi",
) -> str:
    """Plan driving route.
    
    Plan driving route between two points, supports waypoints.
    
    Args:
        origin: Origin coordinates, format "longitude,latitude"
        destination: Destination coordinates, format "longitude,latitude"
        waypoints: Optional, waypoint coordinates, multiple separated by ";", max 16
        strategy: Driving strategy, default 32 (Amap recommended)
            - 32: Amap recommended
            - 33: Avoid congestion
            - 34: Highway priority
            - 35: No highway
            - 36: Less toll
            - 37: Main road priority
            - 38: Fastest speed
        show_fields: Return field control, default includes cost, traffic, navigation info
    
    Returns:
        JSON string containing route info including distance, time, step-by-step instructions
    """
    key = get_amap_key()
    
    params = {
        "key": key,
        "origin": origin,
        "destination": destination,
        "strategy": strategy,
        "show_fields": show_fields,
        "output": "JSON",
    }
    
    if waypoints:
        params["waypoints"] = waypoints
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{AMAP_BASE_URL}/v5/direction/driving",
            params=params,
            timeout=15.0,
        )
        response.raise_for_status()
        data = response.json()
    
    if data.get("status") != "1":
        return f"Route planning failed: {data.get('info', 'Unknown error')}"
    
    route = data.get("route", {})
    paths = route.get("paths", [])
    
    if not paths:
        return "No available driving route found"
    
    # Format the main route info
    path = paths[0] if isinstance(paths, list) else paths
    
    result = {
        "origin": route.get("origin", origin),
        "destination": route.get("destination", destination),
        "distance": path.get("distance", "0"),  # Meters
        "restriction": path.get("restriction", False),  # Has traffic restriction
        "steps": [],
    }
    
    # Extract cost info if available
    cost = path.get("cost", {})
    if cost:
        result["cost"] = {
            "duration": cost.get("duration", "0"),  # Seconds
            "tolls": cost.get("tolls", "0"),  # Yuan
            "toll_distance": cost.get("toll_distance", "0"),  # Meters
            "taxi_fee": cost.get("taxi_fee", "0"),  # Yuan
            "traffic_lights": cost.get("traffic_lights", "0"),  # Number of traffic lights
        }
    
    # Extract step-by-step instructions
    steps = path.get("steps", [])
    for i, step in enumerate(steps):
        step_info = {
            "index": i + 1,
            "instruction": step.get("instruction", ""),
            "road_name": step.get("road_name", ""),
            "distance": step.get("step_distance", "0"),
        }
        result["steps"].append(step_info)
    
    import json
    return json.dumps(result, ensure_ascii=False, indent=2)


# Export all tools
AMAP_TOOLS = [
    amap_geocode,
    amap_place_search,
    amap_place_around,
    amap_driving_route,
]