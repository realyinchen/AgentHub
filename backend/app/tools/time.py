from datetime import datetime
from zoneinfo import ZoneInfo
from langchain_core.tools import tool


@tool
def get_current_time(timezone_name: str = "Asia/Singapore") -> str:
    """Get the current time in a specified timezone.

    This tool returns the current local time for any valid timezone. Use this
    when you need accurate, real-time time information.

    Args:
        timezone_name: IANA timezone name, e.g., "Asia/Shanghai", "Asia/Singapore",
                       "UTC", "America/New_York", "Europe/London".
                       Defaults to "Asia/Singapore".

    Returns:
        A formatted string with the current time, e.g., "2026-02-27 14:35:22 SGT"
        If the timezone is invalid, returns an error message with available suggestions.

    Examples:
        >>> get_current_time("Asia/Shanghai")
        "2026-02-27 14:35:22 CST"
        >>> get_current_time("America/New_York")
        "2026-02-27 01:35:22 EST"
    """
    try:
        tz = ZoneInfo(timezone_name)
        now = datetime.now(tz)
        return now.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception as e:
        # Provide helpful error message with suggestions
        error_msg = str(e)
        if "not found" in error_msg.lower() or "invalid" in error_msg.lower():
            # Suggest common timezones
            common_timezones = [
                "Asia/Shanghai",
                "Asia/Singapore",
                "Asia/Tokyo",
                "America/New_York",
                "America/Los_Angeles",
                "Europe/London",
                "Europe/Paris",
                "UTC",
            ]
            suggestions = ", ".join(common_timezones)
            return (
                f"Invalid timezone '{timezone_name}'. Common timezones: {suggestions}"
            )
        return f"Failed to get time: {error_msg}"


# Keep backward compatibility alias
get_current_local_time = get_current_time
