"""Small, opt-in tools for Groq and Cerebras conversation services."""

from __future__ import annotations

import json
import math
import re
from base64 import b64encode
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urljoin
from xml.etree import ElementTree

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_SIMPLE_TOOLS

DEFAULT_GROUPS: tuple[str, ...] = ()
ALL_GROUPS = {
    "weather",
    "web_search",
    "home_assistant",
    "flight_tracker",
    "apple_calendar",
    "google_workspace",
    "spotify",
    "openroute",
}


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    """Build an OpenAI-compatible function definition."""
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": properties or {},
    }
    if required:
        parameters["required"] = required
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


NUMBER = {"type": "number"}
STRING = {"type": "string"}
INTEGER = {"type": "integer"}
BOOLEAN = {"type": "boolean"}

TOOL_GROUPS: dict[str, list[dict[str, Any]]] = {
    "weather": [
        _tool(
            "get_weather",
            "Get current weather plus hourly and daily forecasts for coordinates.",
            {
                "latitude": NUMBER,
                "longitude": NUMBER,
                "location_name": STRING,
                "temperature_unit": {
                    "type": "string",
                    "enum": ["celsius", "fahrenheit"],
                },
                "wind_speed_unit": {
                    "type": "string",
                    "enum": ["kmh", "ms", "mph", "kn"],
                },
                "precipitation_unit": {
                    "type": "string",
                    "enum": ["mm", "inch"],
                },
            },
            ["latitude", "longitude"],
        ),
        _tool(
            "get_weather_by_city",
            "Get current weather and forecasts for a city using Open-Meteo.",
            {
                "city": STRING,
                "country_code": STRING,
                "temperature_unit": STRING,
                "wind_speed_unit": STRING,
                "precipitation_unit": STRING,
            },
            ["city"],
        ),
    ],
    "web_search": [
        _tool(
            "web_search",
            "Search the web with Exa and return relevant titles, URLs, and summaries.",
            {"query": STRING, "num_results": INTEGER},
            ["query"],
        )
    ],
    "home_assistant": [
        _tool(
            "ha_get_overview",
            "Get a Home Assistant overview with version, areas, domains, and entity counts.",
        ),
        _tool(
            "ha_search",
            "Search Home Assistant entities by entity id, name, state, or keyword.",
            {"query": STRING, "limit": INTEGER},
            ["query"],
        ),
        _tool(
            "ha_get_state",
            "Read the current state and attributes of a Home Assistant entity.",
            {"entity_id": STRING},
            ["entity_id"],
        ),
        _tool(
            "ha_call_service",
            "Call an allowlisted Home Assistant device-control service.",
            {
                "domain": STRING,
                "service": STRING,
                "entity_id": STRING,
                "service_data": {"type": "object"},
            },
            ["domain", "service"],
        ),
    ],
    "flight_tracker": [
        _tool(
            "get_overhead_flights",
            "Get aircraft currently near a location using OpenSky Network.",
            {"latitude": NUMBER, "longitude": NUMBER, "radius_km": NUMBER},
            ["latitude", "longitude"],
        ),
        _tool(
            "get_states_in_bbox",
            "Get aircraft within a geographic bounding box using OpenSky Network.",
            {
                "min_lat": NUMBER,
                "max_lat": NUMBER,
                "min_lon": NUMBER,
                "max_lon": NUMBER,
            },
            ["min_lat", "max_lat", "min_lon", "max_lon"],
        ),
    ],
    "apple_calendar": [
        _tool("calendar_list_calendars", "List Apple iCloud CalDAV calendars."),
        _tool(
            "calendar_get_events",
            "Read Apple Calendar events in a date range.",
            {
                "calendar_url": STRING,
                "start_date": STRING,
                "end_date": STRING,
                "days": INTEGER,
                "max_results": INTEGER,
            },
        ),
    ],
    "google_workspace": [
        _tool(
            "google_get_calendar_events",
            "Get upcoming Google Calendar events from a calendar.",
            {
                "days": INTEGER,
                "max_results": INTEGER,
                "calendar_id": STRING,
                "start_date": STRING,
                "end_date": STRING,
            },
        ),
        _tool(
            "google_search_contacts",
            "Search Google Contacts by name, email, or phone.",
            {"query": STRING, "limit": INTEGER},
            ["query"],
        ),
        _tool(
            "google_search_emails",
            "Search Gmail using Gmail query syntax.",
            {"query": STRING, "max_results": INTEGER, "detail_limit": INTEGER},
        ),
        _tool("google_list_task_lists", "List Google Tasks task lists."),
        _tool(
            "google_list_tasks",
            "List tasks from a Google Tasks list.",
            {"task_list_id": STRING, "show_completed": BOOLEAN, "max_results": INTEGER},
        ),
        _tool(
            "google_create_task",
            "Create a Google Task or reminder.",
            {"title": STRING, "notes": STRING, "due": STRING, "task_list_id": STRING},
            ["title"],
        ),
        _tool(
            "google_complete_task",
            "Mark a Google Task as completed.",
            {"task_id": STRING, "task_list_id": STRING},
            ["task_id"],
        ),
    ],
    "spotify": [
        _tool(
            "spotify_search",
            "Search Spotify for tracks, albums, artists, playlists, episodes, or shows.",
            {"query": STRING, "type": STRING, "limit": INTEGER},
            ["query", "type"],
        ),
        _tool(
            "spotify_get_now_playing",
            "Get the currently playing Spotify track and device.",
        ),
        _tool(
            "spotify_get_playlists",
            "List the user's Spotify playlists.",
            {"limit": INTEGER, "offset": INTEGER},
        ),
        _tool(
            "spotify_get_playlist_tracks",
            "Get tracks from a Spotify playlist.",
            {"playlistId": STRING, "limit": INTEGER, "offset": INTEGER},
            ["playlistId"],
        ),
        _tool(
            "spotify_get_recently_played",
            "Get recently played Spotify tracks.",
            {"limit": INTEGER},
        ),
        _tool(
            "spotify_get_saved_tracks",
            "Get the user's liked songs.",
            {"limit": INTEGER, "offset": INTEGER},
        ),
        _tool("spotify_get_queue", "Get the current Spotify queue."),
        _tool("spotify_get_devices", "List available Spotify Connect devices."),
        _tool(
            "spotify_play",
            "Start Spotify playback.",
            {"uri": STRING, "type": STRING, "id": STRING, "deviceId": STRING},
        ),
        _tool("spotify_pause", "Pause Spotify playback.", {"deviceId": STRING}),
        _tool("spotify_resume", "Resume Spotify playback.", {"deviceId": STRING}),
        _tool(
            "spotify_skip_next", "Skip to the next Spotify track.", {"deviceId": STRING}
        ),
        _tool(
            "spotify_skip_previous",
            "Skip to the previous Spotify track.",
            {"deviceId": STRING},
        ),
        _tool(
            "spotify_add_to_queue",
            "Add a Spotify track URI to the queue.",
            {"uri": STRING, "type": STRING, "id": STRING, "deviceId": STRING},
        ),
        _tool(
            "spotify_set_volume",
            "Set Spotify playback volume from 0 to 100.",
            {"volumePercent": NUMBER, "deviceId": STRING},
            ["volumePercent"],
        ),
        _tool(
            "spotify_adjust_volume",
            "Adjust Spotify volume by a relative amount.",
            {"adjustment": NUMBER, "deviceId": STRING},
            ["adjustment"],
        ),
    ],
    "openroute": [
        _tool(
            "openroute_geocode",
            "Find coordinates for a place or address using OpenRouteService.",
            {"location": STRING},
            ["location"],
        ),
        _tool(
            "openroute_reverse_geocode",
            "Find addresses or place names near coordinates using OpenRouteService.",
            {"lon": NUMBER, "lat": NUMBER},
            ["lon", "lat"],
        ),
    ],
}

TOOL_TO_GROUP = {
    definition["function"]["name"]: group
    for group, definitions in TOOL_GROUPS.items()
    for definition in definitions
}

ALLOWED_HA_SERVICES = {
    "light": {"turn_on", "turn_off", "toggle"},
    "switch": {"turn_on", "turn_off", "toggle"},
    "fan": {"turn_on", "turn_off", "toggle", "set_percentage"},
    "cover": {"open_cover", "close_cover", "stop_cover", "set_cover_position"},
    "lock": {"lock", "unlock"},
    "climate": {"turn_on", "turn_off", "set_temperature", "set_hvac_mode"},
    "media_player": {
        "turn_on",
        "turn_off",
        "media_play",
        "media_pause",
        "media_stop",
        "media_next_track",
        "media_previous_track",
        "volume_set",
        "play_media",
    },
    "scene": {"turn_on"},
    "script": {"turn_on"},
    "automation": {"trigger", "turn_on", "turn_off"},
    "input_boolean": {"turn_on", "turn_off", "toggle"},
    "button": {"press"},
    "vacuum": {"start", "stop", "return_to_base"},
}


def _safe_config(service_data: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized simple-tools configuration object."""
    configured = service_data.get(CONF_SIMPLE_TOOLS)
    if not isinstance(configured, dict):
        return {}
    return dict(configured)


class SimpleToolRegistry:
    """Expose and execute the intentionally small tool set."""

    def __init__(self, hass: HomeAssistant, service_data: dict[str, Any]) -> None:
        self.hass = hass
        self.config = _safe_config(service_data)
        enabled = self.config.get("enabled", DEFAULT_GROUPS)
        if isinstance(enabled, str):
            enabled = [enabled]
        self.enabled = set(enabled) & ALL_GROUPS if isinstance(enabled, list) else set()
        self._apply_credential_guards()

    def _apply_credential_guards(self) -> None:
        required = {
            "web_search": ("exa_api_key",),
            "apple_calendar": ("apple_calendar_email", "apple_calendar_app_password"),
            "google_workspace": ("google_access_token",),
            "spotify": ("spotify_access_token",),
            "openroute": ("openroute_api_key",),
        }
        for group, keys in required.items():
            if group in self.enabled and not all(self.config.get(key) for key in keys):
                self.enabled.remove(group)

    @property
    def definitions(self) -> list[dict[str, Any]]:
        """Return definitions for enabled, configured groups."""
        return [
            definition
            for group in TOOL_GROUPS
            if group in self.enabled
            for definition in TOOL_GROUPS[group]
        ]

    def handles(self, name: str) -> bool:
        """Return whether this registry owns an enabled tool."""
        return TOOL_TO_GROUP.get(name) in self.enabled

    async def async_execute(self, name: str, args: dict[str, Any]) -> Any:
        """Execute a configured simple tool."""
        if not self.handles(name):
            raise ValueError(f"Simple tool is not enabled: {name}")
        group = TOOL_TO_GROUP[name]
        handler = getattr(self, f"_async_{group}")
        return await handler(name, args)

    async def _async_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        payload: Any = None,
    ) -> Any:
        """Issue a JSON request through Home Assistant's shared session."""
        session = async_get_clientsession(self.hass)
        clean_params = {
            key: value for key, value in (params or {}).items() if value is not None
        }
        async with session.request(
            method,
            url,
            headers=headers,
            params=clean_params,
            json=payload,
        ) as response:
            text = await response.text()
            if response.status >= 400:
                raise ValueError(f"HTTP {response.status}: {text[:500]}")
            if not text:
                return {"ok": True, "status": response.status}
            return json.loads(text)

    async def _async_weather(self, name: str, args: dict[str, Any]) -> Any:
        if name == "get_weather_by_city":
            params = {
                "name": args.get("city"),
                "count": 1,
                "language": "en",
                "format": "json",
                "country_code": args.get("country_code"),
            }
            geo = await self._async_json(
                "GET", "https://geocoding-api.open-meteo.com/v1/search", params=params
            )
            results = geo.get("results") or []
            if not results:
                return {"error": f"City not found: {args.get('city', '')}"}
            place = results[0]
            args = {
                **args,
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "location_name": ", ".join(
                    str(place[key])
                    for key in ("name", "admin1", "country")
                    if place.get(key)
                ),
            }
        params = {
            "latitude": args.get("latitude"),
            "longitude": args.get("longitude"),
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,wind_direction_10m",
            "hourly": "temperature_2m,precipitation,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
            "temperature_unit": args.get("temperature_unit", "celsius"),
            "wind_speed_unit": args.get("wind_speed_unit", "kmh"),
            "precipitation_unit": args.get("precipitation_unit", "mm"),
            "timezone": "auto",
            "forecast_days": 7,
        }
        data = await self._async_json(
            "GET", "https://api.open-meteo.com/v1/forecast", params=params
        )
        data["location_name"] = args.get("location_name")
        if isinstance(data.get("hourly"), dict):
            for key, value in data["hourly"].items():
                if isinstance(value, list):
                    data["hourly"][key] = value[:24]
        return data

    async def _async_web_search(self, name: str, args: dict[str, Any]) -> Any:
        return await self._async_json(
            "POST",
            "https://api.exa.ai/search",
            headers={"x-api-key": str(self.config["exa_api_key"])},
            payload={
                "query": str(args.get("query", "")),
                "numResults": max(1, min(int(args.get("num_results", 8)), 20)),
                "contents": {"text": {"maxCharacters": 2000}},
            },
        )

    async def _async_home_assistant(self, name: str, args: dict[str, Any]) -> Any:
        if name == "ha_get_overview":
            counts = Counter(state.domain for state in self.hass.states.async_all())
            area_registry = getattr(self.hass, "data", {}).get("area_registry")
            return {
                "version": getattr(self.hass.config, "version", None),
                "location_name": self.hass.config.location_name,
                "entity_count": sum(counts.values()),
                "domains": dict(sorted(counts.items())),
                "areas": len(getattr(area_registry, "areas", {}) or {}),
            }
        if name == "ha_search":
            query = str(args.get("query", "")).casefold()
            limit = max(1, min(int(args.get("limit", 20)), 100))
            matches = []
            for state in self.hass.states.async_all():
                friendly_name = str(state.attributes.get("friendly_name", ""))
                haystack = f"{state.entity_id} {friendly_name} {state.state}".casefold()
                if query in haystack:
                    matches.append(
                        {
                            "entity_id": state.entity_id,
                            "name": friendly_name or None,
                            "state": state.state,
                        }
                    )
                    if len(matches) >= limit:
                        break
            return {
                "query": args.get("query"),
                "count": len(matches),
                "results": matches,
            }
        if name == "ha_get_state":
            entity_id = str(args.get("entity_id", ""))
            state = self.hass.states.get(entity_id)
            if state is None:
                return {"error": f"Entity not found: {entity_id}"}
            return {
                "entity_id": state.entity_id,
                "state": state.state,
                "attributes": dict(state.attributes),
                "last_changed": state.last_changed.isoformat(),
                "last_updated": state.last_updated.isoformat(),
            }
        domain = str(args.get("domain", ""))
        service = str(args.get("service", ""))
        if service not in ALLOWED_HA_SERVICES.get(domain, set()):
            raise ValueError(f"Service is not allowlisted: {domain}.{service}")
        service_data = dict(args.get("service_data") or {})
        if args.get("entity_id") and "entity_id" not in service_data:
            service_data["entity_id"] = args["entity_id"]
        await self.hass.services.async_call(
            domain, service, service_data, blocking=True
        )
        return {"ok": True, "service": f"{domain}.{service}", "data": service_data}

    async def _async_flight_tracker(self, name: str, args: dict[str, Any]) -> Any:
        latitude: float | None
        longitude: float | None
        radius: float | None
        if name == "get_overhead_flights":
            latitude = float(args["latitude"])
            longitude = float(args["longitude"])
            radius = max(1.0, min(float(args.get("radius_km", 10)), 250.0))
            lat_delta = radius / 111.0
            lon_delta = radius / max(1.0, 111.0 * math.cos(math.radians(latitude)))
            bounds = {
                "min_lat": latitude - lat_delta,
                "max_lat": latitude + lat_delta,
                "min_lon": longitude - lon_delta,
                "max_lon": longitude + lon_delta,
            }
        else:
            bounds = args
            latitude = longitude = radius = None
        data = await self._async_json(
            "GET",
            "https://opensky-network.org/api/states/all",
            params={
                "lamin": bounds.get("min_lat"),
                "lamax": bounds.get("max_lat"),
                "lomin": bounds.get("min_lon"),
                "lomax": bounds.get("max_lon"),
            },
        )
        flights = []
        for state in data.get("states") or []:
            if len(state) < 14:
                continue
            item = {
                "icao24": state[0],
                "callsign": str(state[1] or "").strip() or None,
                "country": state[2],
                "longitude": state[5],
                "latitude": state[6],
                "altitude_m": state[7],
                "on_ground": state[8],
                "velocity_m_s": state[9],
                "heading": state[10],
                "vertical_rate_m_s": state[11],
                "squawk": state[14] if len(state) > 14 else None,
            }
            if (
                latitude is not None
                and longitude is not None
                and radius is not None
                and state[5] is not None
                and state[6] is not None
            ):
                item["distance_km"] = round(
                    _distance_km(latitude, longitude, float(state[6]), float(state[5])),
                    1,
                )
                if item["distance_km"] > radius:
                    continue
            flights.append(item)
        flights.sort(key=lambda item: item.get("distance_km", 0))
        return {"count": len(flights), "flights": flights[:100]}

    async def _async_apple_calendar(self, name: str, args: dict[str, Any]) -> Any:
        calendars = await self._async_apple_calendars()
        if name == "calendar_list_calendars":
            return {"calendars": calendars}
        calendar_url = args.get("calendar_url")
        targets = [
            calendar for calendar in calendars if calendar["url"] == calendar_url
        ]
        if not targets:
            targets = calendars
        start = _parse_date(args.get("start_date")) or datetime.now(UTC)
        end = _parse_date(args.get("end_date")) or start + timedelta(
            days=int(args.get("days", 7))
        )
        max_results = max(1, min(int(args.get("max_results", 50)), 200))
        events: list[dict[str, Any]] = []
        for calendar in targets:
            events.extend(await self._async_apple_events(calendar["url"], start, end))
            if len(events) >= max_results:
                break
        return {"events": events[:max_results]}

    async def _async_caldav(
        self, method: str, url: str, body: str, *, depth: str | None = None
    ) -> str:
        session = async_get_clientsession(self.hass)
        headers = {"content-type": "application/xml; charset=utf-8"}
        if depth is not None:
            headers["depth"] = depth
        credentials = b64encode(
            (
                f"{self.config['apple_calendar_email']}:"
                f"{self.config['apple_calendar_app_password']}"
            ).encode()
        ).decode()
        headers["authorization"] = f"Basic {credentials}"
        async with session.request(
            method,
            url,
            headers=headers,
            data=body,
        ) as response:
            text = await response.text()
            if response.status >= 400:
                raise ValueError(f"CalDAV HTTP {response.status}: {text[:500]}")
            return text

    async def _async_apple_calendars(self) -> list[dict[str, str]]:
        base = str(self.config.get("apple_calendar_url", "https://caldav.icloud.com/"))
        principal_xml = await self._async_caldav(
            "PROPFIND",
            base,
            "<?xml version='1.0'?><d:propfind xmlns:d='DAV:'><d:prop><d:current-user-principal/></d:prop></d:propfind>",
            depth="0",
        )
        principal = _xml_href(principal_xml, "current-user-principal")
        principal_url = urljoin(base, principal or "")
        home_xml = await self._async_caldav(
            "PROPFIND",
            principal_url,
            "<?xml version='1.0'?><d:propfind xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'><d:prop><c:calendar-home-set/></d:prop></d:propfind>",
            depth="0",
        )
        home = _xml_href(home_xml, "calendar-home-set")
        home_url = urljoin(base, home or principal or "")
        listing = await self._async_caldav(
            "PROPFIND",
            home_url,
            "<?xml version='1.0'?><d:propfind xmlns:d='DAV:'><d:prop><d:displayname/><d:resourcetype/></d:prop></d:propfind>",
            depth="1",
        )
        root = ElementTree.fromstring(listing)
        calendars = []
        for response in root.findall("{DAV:}response"):
            resource_type = response.find(".//{DAV:}resourcetype")
            if resource_type is None or not any(
                child.tag.endswith("calendar") for child in resource_type
            ):
                continue
            href = response.findtext("{DAV:}href")
            name = response.findtext(".//{DAV:}displayname") or href
            if href:
                calendars.append(
                    {"name": name or "Calendar", "url": urljoin(base, href)}
                )
        return calendars

    async def _async_apple_events(
        self, url: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        body = (
            "<?xml version='1.0'?><c:calendar-query xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'>"
            "<d:prop><d:getetag/><c:calendar-data/></d:prop><c:filter><c:comp-filter name='VCALENDAR'>"
            f"<c:comp-filter name='VEVENT'><c:time-range start='{start.strftime('%Y%m%dT%H%M%SZ')}' end='{end.strftime('%Y%m%dT%H%M%SZ')}'/>"
            "</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>"
        )
        xml = await self._async_caldav("REPORT", url, body, depth="1")
        root = ElementTree.fromstring(xml)
        events = []
        for data in root.findall(".//{urn:ietf:params:xml:ns:caldav}calendar-data"):
            events.extend(_parse_ics_events(data.text or ""))
        return events

    async def _async_google_workspace(self, name: str, args: dict[str, Any]) -> Any:
        token = str(self.config["google_access_token"])
        headers = {"authorization": f"Bearer {token}"}
        if name == "google_get_calendar_events":
            start = _parse_date(args.get("start_date")) or datetime.now(UTC)
            end = _parse_date(args.get("end_date")) or start + timedelta(
                days=int(args.get("days", 7))
            )
            calendar_id = quote(str(args.get("calendar_id", "primary")), safe="")
            return await self._async_json(
                "GET",
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
                headers=headers,
                params={
                    "timeMin": start.isoformat(),
                    "timeMax": end.isoformat(),
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": min(int(args.get("max_results", 20)), 100),
                },
            )
        if name == "google_search_contacts":
            return await self._async_json(
                "GET",
                "https://people.googleapis.com/v1/people:searchContacts",
                headers=headers,
                params={
                    "query": args.get("query"),
                    "readMask": "names,emailAddresses,phoneNumbers",
                    "pageSize": min(int(args.get("limit", 20)), 30),
                },
            )
        if name == "google_search_emails":
            messages = await self._async_json(
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                headers=headers,
                params={
                    "q": args.get("query", "newer_than:7d"),
                    "maxResults": min(int(args.get("max_results", 10)), 50),
                },
            )
            details = []
            for item in (messages.get("messages") or [])[
                : min(int(args.get("detail_limit", 5)), 10)
            ]:
                details.append(
                    await self._async_json(
                        "GET",
                        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{item['id']}",
                        headers=headers,
                        params={
                            "format": "metadata",
                            "metadataHeaders": ["From", "To", "Subject", "Date"],
                        },
                    )
                )
            return {**messages, "details": details}
        task_list_id = quote(str(args.get("task_list_id", "@default")), safe="")
        if name == "google_list_task_lists":
            return await self._async_json(
                "GET",
                "https://tasks.googleapis.com/tasks/v1/users/@me/lists",
                headers=headers,
            )
        task_url = f"https://tasks.googleapis.com/tasks/v1/lists/{task_list_id}/tasks"
        if name == "google_list_tasks":
            return await self._async_json(
                "GET",
                task_url,
                headers=headers,
                params={
                    "showCompleted": str(
                        bool(args.get("show_completed", False))
                    ).lower(),
                    "showHidden": str(bool(args.get("show_completed", False))).lower(),
                    "maxResults": min(int(args.get("max_results", 50)), 100),
                },
            )
        if name == "google_create_task":
            return await self._async_json(
                "POST",
                task_url,
                headers=headers,
                payload={
                    key: args[key] for key in ("title", "notes", "due") if args.get(key)
                },
            )
        task_id = quote(str(args["task_id"]), safe="")
        current = await self._async_json(
            "GET", f"{task_url}/{task_id}", headers=headers
        )
        current["status"] = "completed"
        current["completed"] = datetime.now(UTC).isoformat()
        return await self._async_json(
            "PUT", f"{task_url}/{task_id}", headers=headers, payload=current
        )

    async def _async_spotify(self, name: str, args: dict[str, Any]) -> Any:
        headers = {"authorization": f"Bearer {self.config['spotify_access_token']}"}
        base = "https://api.spotify.com/v1"
        get_routes = {
            "spotify_get_now_playing": ("/me/player/currently-playing", {}),
            "spotify_get_playlists": (
                "/me/playlists",
                {"limit": args.get("limit", 20), "offset": args.get("offset", 0)},
            ),
            "spotify_get_playlist_tracks": (
                f"/playlists/{quote(str(args.get('playlistId', '')), safe='')}/tracks",
                {"limit": args.get("limit", 50), "offset": args.get("offset", 0)},
            ),
            "spotify_get_recently_played": (
                "/me/player/recently-played",
                {"limit": args.get("limit", 20)},
            ),
            "spotify_get_saved_tracks": (
                "/me/tracks",
                {"limit": args.get("limit", 20), "offset": args.get("offset", 0)},
            ),
            "spotify_get_queue": ("/me/player/queue", {}),
            "spotify_get_devices": ("/me/player/devices", {}),
        }
        if name == "spotify_search":
            return await self._async_json(
                "GET",
                f"{base}/search",
                headers=headers,
                params={
                    "q": args.get("query"),
                    "type": args.get("type"),
                    "limit": min(int(args.get("limit", 10)), 50),
                },
            )
        if name in get_routes:
            route, params = get_routes[name]
            return await self._async_json(
                "GET", f"{base}{route}", headers=headers, params=params
            )
        device = args.get("deviceId")
        device_params = {"device_id": device} if device else None
        if name in {"spotify_pause", "spotify_resume", "spotify_play"}:
            route = "/me/player/pause" if name == "spotify_pause" else "/me/player/play"
            payload = None
            if name == "spotify_play":
                uri = args.get("uri") or (
                    f"spotify:{args.get('type')}:{args.get('id')}"
                    if args.get("type") and args.get("id")
                    else None
                )
                if uri:
                    payload = (
                        {"uris": [uri]}
                        if str(uri).startswith("spotify:track:")
                        else {"context_uri": uri}
                    )
            return await self._async_json(
                "PUT",
                f"{base}{route}",
                headers=headers,
                params=device_params,
                payload=payload,
            )
        if name in {"spotify_skip_next", "spotify_skip_previous"}:
            route = (
                "/me/player/next"
                if name == "spotify_skip_next"
                else "/me/player/previous"
            )
            return await self._async_json(
                "POST", f"{base}{route}", headers=headers, params=device_params
            )
        if name == "spotify_add_to_queue":
            uri = args.get("uri") or (
                f"spotify:{args.get('type')}:{args.get('id')}"
                if args.get("type") and args.get("id")
                else None
            )
            return await self._async_json(
                "POST",
                f"{base}/me/player/queue",
                headers=headers,
                params={"uri": uri, **(device_params or {})},
            )
        volume = float(args.get("volumePercent", 0))
        if name == "spotify_adjust_volume":
            playback = await self._async_json(
                "GET", f"{base}/me/player", headers=headers
            )
            volume = float(
                (playback.get("device") or {}).get("volume_percent", 0)
            ) + float(args.get("adjustment", 0))
        return await self._async_json(
            "PUT",
            f"{base}/me/player/volume",
            headers=headers,
            params={
                "volume_percent": max(0, min(round(volume), 100)),
                **(device_params or {}),
            },
        )

    async def _async_openroute(self, name: str, args: dict[str, Any]) -> Any:
        headers = {"authorization": str(self.config["openroute_api_key"])}
        if name == "openroute_geocode":
            return await self._async_json(
                "GET",
                "https://api.openrouteservice.org/geocode/search",
                headers=headers,
                params={"text": args.get("location"), "size": 5},
            )
        return await self._async_json(
            "GET",
            "https://api.openrouteservice.org/geocode/reverse",
            headers=headers,
            params={
                "point.lon": args.get("lon"),
                "point.lat": args.get("lat"),
                "size": 5,
            },
        )


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in kilometres."""
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(delta_lon / 2) ** 2
    )
    return 6371.0 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _parse_date(value: Any) -> datetime | None:
    """Parse an ISO date/time into an aware UTC datetime."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _xml_href(xml: str, property_name: str) -> str | None:
    """Return the first DAV href below a property element."""
    root = ElementTree.fromstring(xml)
    for element in root.iter():
        if element.tag.endswith(property_name):
            for child in element.iter():
                if child.tag.endswith("href") and child.text:
                    return child.text
    return None


def _parse_ics_events(ics: str) -> list[dict[str, Any]]:
    """Parse the small VEVENT field subset needed for calendar answers."""
    unfolded = re.sub(r"\r?\n[ \t]", "", ics)
    events = []
    for block in re.findall(
        r"BEGIN:VEVENT\r?\n(.*?)\r?\nEND:VEVENT", unfolded, re.DOTALL
    ):
        event: dict[str, Any] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            raw_key, value = line.split(":", 1)
            key = raw_key.split(";", 1)[0]
            mapped = {
                "UID": "id",
                "SUMMARY": "summary",
                "DTSTART": "start",
                "DTEND": "end",
                "LOCATION": "location",
                "DESCRIPTION": "description",
                "URL": "url",
            }.get(key)
            if mapped:
                event[mapped] = value.replace("\\n", "\n").replace("\\,", ",")
        if event:
            events.append(event)
    return events
