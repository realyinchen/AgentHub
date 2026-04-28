"""Amap (Gaode Map) API tools for navigator agent.

This module provides LangChain tools for interacting with Amap API:
- amap_geocode: Convert address to coordinates
- amap_place_search: Search POI by keywords
- amap_place_around: Search POI around a location
- amap_driving_route: Plan driving route
- amap_route_preview: Generate route preview URL with waypoints
- amap_weather: Query weather information

Navigation Links:
- Uses Amap URI API: https://lbs.amap.com/api/amap-uri/guide/route
- Web navigation: https://uri.amap.com/navigation?from=...&to=...&mode=car
"""

import httpx
from langchain_core.tools import tool
from typing import Any, Optional
from urllib.parse import quote

from app.core.config import settings


# Amap API base URL
AMAP_BASE_URL = "https://restapi.amap.com"

# Amap URI scheme for web navigation
AMAP_URI_BASE = "https://uri.amap.com"


def _generate_navigation_url(
    destination: str,
    origin: Optional[str] = None,
    mode: str = "car",
    dest_name: Optional[str] = None,
    origin_name: Optional[str] = None,
    waypoints: Optional[list[str]] = None,
    waypoint_names: Optional[list[str]] = None,
) -> str:
    """Generate Amap navigation URL for web browser.

    Args:
        destination: Destination coordinates "longitude,latitude"
        origin: Origin coordinates "longitude,latitude", optional
        mode: Navigation mode - "car", "walk", "ride", "transit"
        dest_name: Destination name for display
        origin_name: Origin name for display
        waypoints: List of waypoint coordinates ["lon,lat", ...]
        waypoint_names: List of waypoint names for display

    Returns:
        Amap URI for navigation

    Note:
        Amap URI API format:
        https://uri.amap.com/navigation?from=lon,lat,name&to=lon,lat,name&mode=car&coordinate=gaode&via=lon,lat,name;lon,lat,name
    """
    # Build from parameter: lon,lat,name
    if origin:
        if origin_name:
            from_value = f"{origin},{origin_name}"
        else:
            from_value = origin
    else:
        from_value = None

    # Build to parameter: lon,lat,name
    if dest_name:
        to_value = f"{destination},{dest_name}"
    else:
        to_value = destination

    # Build via parameter: lon,lat,name;lon,lat,name;...
    via_value = None
    if waypoints:
        via_points = []
        for i, wp in enumerate(waypoints):
            if waypoint_names and i < len(waypoint_names) and waypoint_names[i]:
                via_points.append(f"{wp},{waypoint_names[i]}")
            else:
                via_points.append(wp)
        via_value = ";".join(via_points)

    # Build URL with proper encoding
    # Note: We need to encode the values but keep the delimiters (; ,) unencoded
    query_parts = [
        f"to={quote(to_value, safe=',')}",
        f"mode={mode}",
        "coordinate=gaode",
    ]

    if from_value:
        query_parts.insert(0, f"from={quote(from_value, safe=',')}")

    if via_value:
        # For via parameter, keep ; and , unencoded as they are delimiters
        query_parts.append(f"via={quote(via_value, safe=';,')}")

    query_string = "&".join(query_parts)
    return f"{AMAP_URI_BASE}/navigation?{query_string}"


def _generate_route_preview_url(
    origin: str,
    destination: str,
    waypoints: Optional[list[str]] = None,
    origin_name: Optional[str] = None,
    dest_name: Optional[str] = None,
    waypoint_names: Optional[list[str]] = None,
) -> str:
    """Generate Amap URL to preview a complete route with all waypoints on map.

    This creates a URL that shows the entire route on the map, including all waypoints.
    Useful for displaying a multi-stop journey in a single view.

    Args:
        origin: Origin coordinates "longitude,latitude"
        destination: Destination coordinates "longitude,latitude"
        waypoints: List of intermediate waypoint coordinates
        origin_name: Origin name for display
        dest_name: Destination name for display
        waypoint_names: List of waypoint names for display

    Returns:
        Amap URI for route preview

    Note:
        This function directly calls _generate_navigation_url with all waypoints.
        The generated URL format:
        https://uri.amap.com/navigation?from=lon,lat,name&to=lon,lat,name&via=lon,lat,name;lon,lat,name&mode=car&coordinate=gaode
    """
    # Directly use the navigation URL with all waypoints
    return _generate_navigation_url(
        destination=destination,
        origin=origin,
        mode="car",
        dest_name=dest_name,
        origin_name=origin_name,
        waypoints=waypoints,
        waypoint_names=waypoint_names,
    )


def _generate_map_url(location: str, name: Optional[str] = None) -> str:
    """Generate Amap URL to view a location on map.

    Args:
        location: Coordinates "longitude,latitude"
        name: Place name for display

    Returns:
        Amap URI for viewing location
    """
    if name:
        return f"{AMAP_URI_BASE}/marker?position={location}&name={name}"
    return f"{AMAP_URI_BASE}/marker?position={location}"


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
        location = geo.get("location", "")
        formatted_address = geo.get("formatted_address", "")
        results.append(
            {
                "formatted_address": formatted_address,
                "location": location,
                "province": geo.get("province", ""),
                "city": geo.get("city", ""),
                "district": geo.get("district", ""),
                "level": geo.get("level", ""),
                "map_url": _generate_map_url(location, formatted_address)
                if location
                else "",
            }
        )

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
        location = poi.get("location", "")
        name = poi.get("name", "")
        results.append(
            {
                "id": poi.get("id", ""),
                "name": name,
                "type": poi.get("type", ""),
                "typecode": poi.get("typecode", ""),
                "address": poi.get("address", ""),
                "location": location,
                "pname": poi.get("pname", ""),  # Province
                "cityname": poi.get("cityname", ""),  # City
                "adname": poi.get("adname", ""),  # District
                "tel": poi.get("tel", ""),
                "rating": poi.get("biz_ext", {}).get("rating", ""),
                "cost": poi.get("biz_ext", {}).get("cost", ""),
                "map_url": _generate_map_url(location, name) if location else "",
            }
        )

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
        poi_location = poi.get("location", "")
        poi_name = poi.get("name", "")
        results.append(
            {
                "id": poi.get("id", ""),
                "name": poi_name,
                "type": poi.get("type", ""),
                "address": poi.get("address", ""),
                "location": poi_location,
                "distance": poi.get("distance", ""),  # Distance from center (meters)
                "pname": poi.get("pname", ""),
                "cityname": poi.get("cityname", ""),
                "adname": poi.get("adname", ""),
                "tel": poi.get("tel", ""),
                "rating": poi.get("biz_ext", {}).get("rating", ""),
                "map_url": _generate_map_url(poi_location, poi_name)
                if poi_location
                else "",
            }
        )

    import json

    result_data = {
        "center": location,
        "radius": radius,
        "count": data.get("count", "0"),
        "pois": results,
    }
    return json.dumps(result_data, ensure_ascii=False, indent=2)


def _generate_static_map_url_from_route(
    origin: str,
    destination: str,
    waypoints: Optional[list[str]] = None,
    polyline_points: Optional[list[str]] = None,
    origin_name: Optional[str] = None,
    dest_name: Optional[str] = None,
    waypoint_names: Optional[list[str]] = None,
    width: int = 600,
    height: int = 400,
) -> str:
    """Generate static map URL showing the route with markers and path.

    Args:
        origin: Origin coordinates "longitude,latitude"
        destination: Destination coordinates "longitude,latitude"
        waypoints: List of waypoint coordinates
        polyline_points: List of polyline points from route steps (real route)
        origin_name: Origin name for display
        dest_name: Destination name for display
        waypoint_names: List of waypoint names for display
        width: Image width in pixels
        height: Image height in pixels

    Returns:
        Static map image URL

    Note:
        Amap static map markers format:
        - markers=size,color,label:location1;location2...|size,color,label:location3...
        - label only supports [0-9], [A-Z]
        - Same style points separated by ";", different styles separated by "|"
    """
    key = get_amap_key()

    # Build markers with correct format
    # Labels: A=Start, B=End, C/D/E...=Waypoints (only A-Z are valid)
    marker_groups = []

    # Origin marker (green, label "A")
    marker_groups.append(f"mid,0x008000,A:{origin}")

    # Waypoint markers (orange, labels C, D, E...)
    # Skip "B" for destination, so waypoints start from "C"
    if waypoints:
        waypoint_labels = "CDEFGHIJ"  # Max 8 waypoints supported (C-J)
        for i, wp in enumerate(waypoints):
            if i < len(waypoint_labels):
                label = waypoint_labels[i]
                marker_groups.append(f"mid,0xFF9900,{label}:{wp}")

    # Destination marker (red, label "B")
    marker_groups.append(f"mid,0xFF0000,B:{destination}")

    # Join with "|" - different styles separated by "|"
    markers_param = "|".join(marker_groups)

    # Build paths parameter using real polyline if available
    paths_param = None
    if polyline_points and len(polyline_points) >= 2:
        # Sample points if too many (URL length limit)
        max_points = 150
        if len(polyline_points) > max_points:
            step = len(polyline_points) // max_points
            sampled_points = polyline_points[::step]
            # Always include the last point
            if polyline_points[-1] not in sampled_points:
                sampled_points.append(polyline_points[-1])
            polyline_points = sampled_points

        # Format: weight,color,transparency,fillcolor,fillTransparency:point1;point2;...
        # Note: fillcolor and fillTransparency are optional, use 2 commas to skip them
        # Official example: paths=10,0x0000ff,1,,:116.31604,39.96491;...
        points_str = ";".join(polyline_points)
        paths_param = f"6,0x0080FF,0.9,,:{points_str}"

    # Build URL
    query_parts = [
        f"key={key}",
        f"size={width}*{height}",
        "scale=2",
        f"markers={markers_param}",
    ]

    if paths_param:
        query_parts.append(f"paths={paths_param}")

    query_string = "&".join(query_parts)
    return f"{AMAP_BASE_URL}/v3/staticmap?{query_string}"


@tool
async def amap_driving_route(
    origin: str,
    destination: str,
    waypoints: Optional[str] = None,
    origin_name: Optional[str] = None,
    dest_name: Optional[str] = None,
    waypoint_names: Optional[str] = None,
    strategy: int = 10,
) -> str:
    """Plan driving route with navigation links and static map.

    Plan driving route between two points, supports waypoints. Returns:
    - Static map image URL showing the route
    - Complete route navigation link
    - Segment navigation links for each leg

    Args:
        origin: Origin coordinates, format "longitude,latitude"
        destination: Destination coordinates, format "longitude,latitude"
        waypoints: Optional, waypoint coordinates, multiple separated by ";", max 16
                   Example: "116.123,39.456;117.234,40.567"
        origin_name: Optional, origin name for display in navigation link
        dest_name: Optional, destination name for display in navigation link
        waypoint_names: Optional, waypoint names separated by ";", matching waypoints order
                        Example: "Restaurant;Company"
        strategy: Driving strategy, default 10 (Amap recommended with multiple routes)
            - 10: Amap recommended (returns multiple routes, avoids congestion)
            - 12: Avoid congestion
            - 13: No highway
            - 14: Avoid toll
            - 19: Highway priority

    Returns:
        JSON string containing route info including:
        - static_map_url: URL to a static map image showing the route
        - distance, time, tolls
        - navigation_url: Complete route with all waypoints
        - segment_navigation_urls: List of segment links [A->B, B->C, C->D]
    """
    import json

    key = get_amap_key()

    # Use v3 API to get polyline data
    params = {
        "key": key,
        "origin": origin,
        "destination": destination,
        "extensions": "all",  # Required to get polyline
        "output": "JSON",
    }

    if waypoints:
        params["waypoints"] = waypoints

    if strategy:
        params["strategy"] = str(strategy)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{AMAP_BASE_URL}/v3/direction/driving",
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

    # Format the main route info (use first path)
    path = paths[0] if isinstance(paths, list) else paths

    result = {
        "origin": route.get("origin", origin),
        "destination": route.get("destination", destination),
        "distance": path.get("distance", "0"),  # Meters
        "duration": path.get("duration", "0"),  # Seconds
        "restriction": path.get(
            "restriction", "0"
        ),  # 0=no restriction, 1=has restriction
        "steps": [],
    }

    # Extract cost info
    tolls = path.get("tolls", "0")
    toll_distance = path.get("toll_distance", "0")
    traffic_lights = path.get("traffic_lights", "0")

    result["cost"] = {
        "duration": path.get("duration", "0"),  # Seconds
        "tolls": tolls,  # Yuan
        "toll_distance": toll_distance,  # Meters
        "traffic_lights": traffic_lights,
    }

    # Extract step-by-step instructions and polyline points
    steps = path.get("steps", [])
    all_polyline_points = []

    for i, step in enumerate(steps):
        step_info = {
            "index": i + 1,
            "instruction": step.get("instruction", ""),
            "road": step.get("road", ""),
            "distance": step.get("distance", "0"),
            "duration": step.get("duration", "0"),
        }
        result["steps"].append(step_info)

        # Extract polyline points from this step
        polyline = step.get("polyline", "")
        if polyline:
            points = [p.strip() for p in polyline.split(";") if p.strip()]
            all_polyline_points.extend(points)

    # Parse waypoint names
    wp_names_list = None
    if waypoint_names:
        wp_names_list = [
            name.strip() for name in waypoint_names.split(";") if name.strip()
        ]

    # Parse waypoints list
    wp_list = None
    if waypoints:
        wp_list = [wp.strip() for wp in waypoints.split(";") if wp.strip()]

    # Generate static map URL with real route polyline
    result["static_map_url"] = _generate_static_map_url_from_route(
        origin=origin,
        destination=destination,
        waypoints=wp_list,
        polyline_points=all_polyline_points,
        origin_name=origin_name,
        dest_name=dest_name,
        waypoint_names=wp_names_list,
    )

    # Generate complete navigation URL with all waypoints
    result["navigation_url"] = _generate_navigation_url(
        destination=destination,
        origin=origin,
        mode="car",
        dest_name=dest_name,
        origin_name=origin_name,
        waypoints=wp_list,
        waypoint_names=wp_names_list,
    )

    # Generate segment navigation URLs [A->B, B->C, C->D]
    segment_urls = []
    all_points = [origin]  # Start with origin
    all_names = [origin_name or "起点"]

    if wp_list:
        all_points.extend(wp_list)
        if wp_names_list:
            # Pad names if needed
            all_names.extend(wp_names_list + [""] * (len(wp_list) - len(wp_names_list)))
        else:
            all_names.extend([f"途经点{i + 1}" for i in range(len(wp_list))])

    all_points.append(destination)  # End with destination
    all_names.append(dest_name or "终点")

    # Generate segment URLs
    for i in range(len(all_points) - 1):
        segment_url = _generate_navigation_url(
            destination=all_points[i + 1],
            origin=all_points[i],
            mode="car",
            dest_name=all_names[i + 1],
            origin_name=all_names[i],
        )
        segment_urls.append(
            {
                "from": all_names[i],
                "to": all_names[i + 1],
                "url": segment_url,
            }
        )

    result["segment_navigation_urls"] = segment_urls

    # Generate marker labels for display
    # Format: [{"label": "A", "name": "Start point name", "color": "green"}, ...]
    marker_labels = []

    # Origin (A - green)
    marker_labels.append(
        {
            "label": "A",
            "name": origin_name or "起点",
            "color": "green",
        }
    )

    # Waypoints (C, D, E... - orange)
    if wp_list:
        waypoint_labels = "CDEFGHIJ"
        for i, wp in enumerate(wp_list):
            if i < len(waypoint_labels):
                name = (
                    wp_names_list[i]
                    if wp_names_list and i < len(wp_names_list)
                    else f"途经点{i + 1}"
                )
                marker_labels.append(
                    {
                        "label": waypoint_labels[i],
                        "name": name,
                        "color": "orange",
                    }
                )

    # Destination (B - red)
    marker_labels.append(
        {
            "label": "B",
            "name": dest_name or "终点",
            "color": "red",
        }
    )

    result["marker_labels"] = marker_labels

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
async def amap_static_map(
    markers: list[dict],
    paths: Optional[list[dict]] = None,
    width: int = 600,
    height: int = 400,
    zoom: Optional[int] = None,
    location: Optional[str] = None,
) -> str:
    """Generate a static map image with markers and paths.

    Use this tool to create a visual preview of a route with start point, waypoints,
    and destination marked on the map. The returned URL points to a PNG image.

    Args:
        markers: List of marker points, each dict contains:
            - location: Coordinates "longitude,latitude" (required)
            - label: Label text for the marker (optional, 1-2 chars recommended)
            - color: Marker color in hex, e.g., "0xFF0000" for red (optional)
            - size: Marker size - "small", "mid", "large" (optional, default "mid")
        paths: Optional list of path lines, each dict contains:
            - points: List of coordinates ["lon,lat", "lon,lat", ...]
            - color: Line color in hex, e.g., "0x0000FF" for blue (optional)
            - weight: Line thickness 2-15 (optional, default 5)
            - transparency: Line transparency 0-1 (optional, default 1)
        width: Image width in pixels, max 1024 (default 600)
        height: Image height in pixels, max 1024 (default 400)
        zoom: Map zoom level 1-17 (optional, auto-calculated if not provided)
        location: Map center coordinates (optional, auto-calculated from markers/paths)

    Returns:
        JSON string containing the static map image URL
    """
    import json

    key = get_amap_key()

    params = {
        "key": key,
        "size": f"{min(width, 1024)}*{min(height, 1024)}",
        "scale": 2,  # High resolution
    }

    # Build markers parameter
    # Format: markers=markersStyle1:location1;location2..|markersStyle2:...
    if markers:
        marker_groups = []
        for m in markers:
            loc = m.get("location", "")
            if not loc:
                continue
            size = m.get("size", "mid")
            color = m.get("color", "0xFC6054")
            label = m.get("label", "")

            # Format: size,color,label:location
            marker_style = f"{size},{color}"
            if label:
                marker_style += f",{label}"

            marker_groups.append(f"{marker_style}:{loc}")

        if marker_groups:
            params["markers"] = "|".join(marker_groups)

    # Build paths parameter
    # Format: paths=pathsStyle1:location1;location2..|pathsStyle2:...
    if paths:
        path_groups = []
        for p in paths:
            points = p.get("points", [])
            if not points:
                continue
            weight = p.get("weight", 5)
            color = p.get("color", "0x0000FF")
            transparency = p.get("transparency", 1)

            # Format: weight,color,transparency:point1;point2;...
            path_style = f"{weight},{color},{transparency}"
            points_str = ";".join(points)

            path_groups.append(f"{path_style}:{points_str}")

        if path_groups:
            params["paths"] = "|".join(path_groups)

    # Add zoom and location if provided
    if zoom:
        params["zoom"] = str(min(max(zoom, 1), 17))
    if location:
        params["location"] = location

    # Build URL - only encode special chars, keep delimiters
    # The markers and paths use | and ; as delimiters which should NOT be encoded
    query_parts = []
    for k, v in params.items():
        # Keep | and ; unencoded as they are delimiters for markers/paths
        encoded_value = quote(str(v), safe="|;")
        query_parts.append(f"{k}={encoded_value}")

    query_string = "&".join(query_parts)
    static_map_url = f"{AMAP_BASE_URL}/v3/staticmap?{query_string}"

    result = {
        "static_map_url": static_map_url,
        "width": width,
        "height": height,
        "markers_count": len(markers),
        "paths_count": len(paths) if paths else 0,
    }

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
async def amap_weather(city: str, extensions: str = "base") -> str:
    """Query weather information for a city.

    Get current weather or weather forecast for a city using Amap weather API.
    Use this tool to check weather conditions for outdoor activities.

    Args:
        city: City adcode (administrative division code), e.g., "110000" for Beijing
              Common codes: Beijing=110000, Shanghai=310000, Hefei=340100
              Or use city name like "北京", "上海", "合肥"
        extensions: Weather type, "base" for current weather, "all" for forecast
            - base: Returns current weather (temperature, weather, wind, humidity)
            - all: Returns current + future 4 days forecast

    Returns:
        JSON string containing weather information
    """
    key = get_amap_key()

    params = {
        "key": key,
        "city": city,
        "extensions": extensions,
        "output": "JSON",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{AMAP_BASE_URL}/v3/weather/weatherInfo",
            params=params,
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()

    if data.get("status") != "1":
        return f"Weather query failed: {data.get('info', 'Unknown error')}"

    import json

    # Parse weather data
    result: dict[str, Any] = {"city": city, "status": "success"}

    # Current weather (lives)
    lives = data.get("lives", [])
    if lives:
        current = lives[0]
        result["current"] = {
            "province": current.get("province", ""),
            "city": current.get("city", ""),
            "weather": current.get("weather", ""),  # e.g., "晴", "多云", "小雨"
            "temperature": current.get("temperature", ""),  # Celsius
            "winddirection": current.get("winddirection", ""),  # e.g., "东南"
            "windpower": current.get("windpower", ""),  # e.g., "3", "≤3"
            "humidity": current.get("humidity", ""),  # Percentage
            "reporttime": current.get("reporttime", ""),
        }

    # Forecast (if extensions="all")
    forecasts = data.get("forecasts", [])
    if forecasts:
        forecast_data = forecasts[0]
        casts = forecast_data.get("casts", [])
        result["forecast"] = []
        for cast in casts:
            result["forecast"].append(
                {
                    "date": cast.get("date", ""),
                    "week": cast.get("week", ""),
                    "dayweather": cast.get("dayweather", ""),
                    "nightweather": cast.get("nightweather", ""),
                    "daytemp": cast.get("daytemp", ""),
                    "nighttemp": cast.get("nighttemp", ""),
                    "daywind": cast.get("daywind", ""),
                    "nightwind": cast.get("nightwind", ""),
                    "daypower": cast.get("daypower", ""),
                    "nightpower": cast.get("nightpower", ""),
                }
            )

    return json.dumps(result, ensure_ascii=False, indent=2)


# Export all tools
AMAP_TOOLS = [
    amap_geocode,
    amap_place_search,
    amap_place_around,
    amap_driving_route,
    amap_weather,
]
