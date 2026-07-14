from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.groq.const import CONF_SIMPLE_TOOLS
from custom_components.groq.simple_tools import (
    SimpleToolRegistry,
    _distance_km,
    _parse_date,
    _parse_ics_events,
    _safe_config,
    _xml_href,
)

ALL_TOOL_CONFIG = {
    "enabled": [
        "weather",
        "web_search",
        "home_assistant",
        "flight_tracker",
        "apple_calendar",
        "google_workspace",
        "spotify",
        "openroute",
    ],
    "exa_api_key": "exa",
    "apple_calendar_email": "person@example.com",
    "apple_calendar_app_password": "password",
    "google_access_token": "google",
    "spotify_access_token": "spotify",
    "openroute_api_key": "openroute",
}


def registry(hass: object | None = None) -> SimpleToolRegistry:
    return SimpleToolRegistry(
        hass or SimpleNamespace(), {CONF_SIMPLE_TOOLS: ALL_TOOL_CONFIG}
    )


class FakeResponse:
    def __init__(self, status: int, text: str) -> None:
        self.status = status
        self._text = text

    async def text(self) -> str:
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeSession:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.calls = []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.responses.pop(0)


def test_simple_tool_config_normalization_and_string_group() -> None:
    assert _safe_config({CONF_SIMPLE_TOOLS: "invalid"}) == {}
    configured = SimpleToolRegistry(
        SimpleNamespace(), {CONF_SIMPLE_TOOLS: {"enabled": "weather"}}
    )
    assert configured.handles("get_weather")
    assert not configured.handles("web_search")
    missing_credentials = SimpleToolRegistry(
        SimpleNamespace(),
        {CONF_SIMPLE_TOOLS: {"enabled": ["weather", "web_search"]}},
    )
    assert [
        definition["function"]["name"] for definition in missing_credentials.definitions
    ] == ["get_weather", "get_weather_by_city"]


@pytest.mark.asyncio
async def test_simple_tool_execute_dispatch_and_disabled_error() -> None:
    configured = registry()
    configured._async_weather = AsyncMock(return_value={"ok": True})
    assert await configured.async_execute("get_weather", {}) == {"ok": True}
    configured._async_weather.assert_awaited_once_with("get_weather", {})
    with pytest.raises(ValueError, match="not enabled"):
        await configured.async_execute("unknown", {})


@pytest.mark.asyncio
async def test_json_request_success_empty_and_error() -> None:
    session = FakeSession(
        FakeResponse(200, '{"value":1}'),
        FakeResponse(204, ""),
        FakeResponse(400, "bad request"),
    )
    configured = registry()
    with patch(
        "custom_components.groq.simple_tools.async_get_clientsession",
        return_value=session,
    ):
        assert await configured._async_json(
            "GET", "https://example.test", params={"keep": 1, "drop": None}
        ) == {"value": 1}
        assert await configured._async_json("POST", "https://example.test") == {
            "ok": True,
            "status": 204,
        }
        with pytest.raises(ValueError, match="HTTP 400"):
            await configured._async_json("GET", "https://example.test")
    assert session.calls[0][1]["params"] == {"keep": 1}


@pytest.mark.asyncio
async def test_weather_city_coordinates_and_missing_city() -> None:
    configured = registry()
    configured._async_json = AsyncMock(
        side_effect=[
            {
                "results": [
                    {
                        "name": "Sacramento",
                        "admin1": "California",
                        "country": "United States",
                        "latitude": 38.5,
                        "longitude": -121.5,
                    }
                ]
            },
            {"hourly": {"time": list(range(30)), "unit": "hours"}},
            {"results": []},
            {"current": {"temperature": 80}},
        ]
    )
    result = await configured._async_weather(
        "get_weather_by_city", {"city": "Sacramento", "country_code": "US"}
    )
    assert result["location_name"] == "Sacramento, California, United States"
    assert len(result["hourly"]["time"]) == 24
    assert result["hourly"]["unit"] == "hours"
    assert await configured._async_weather(
        "get_weather_by_city", {"city": "Missing"}
    ) == {"error": "City not found: Missing"}
    assert (
        await configured._async_weather("get_weather", {"latitude": 1, "longitude": 2})
    )["current"] == {"temperature": 80}


@pytest.mark.asyncio
async def test_web_search_limits_results() -> None:
    configured = registry()
    configured._async_json = AsyncMock(return_value={"results": []})
    await configured._async_web_search(
        "web_search", {"query": "Home Assistant", "num_results": 99}
    )
    assert configured._async_json.await_args.kwargs["payload"]["numResults"] == 20


class FakeStates:
    def __init__(self, states):
        self._states = states

    def async_all(self):
        return self._states

    def get(self, entity_id):
        return next(
            (state for state in self._states if state.entity_id == entity_id), None
        )


class FakeServices:
    def __init__(self):
        self.calls = []

    async def async_call(self, domain, service, data, *, blocking):
        self.calls.append((domain, service, data, blocking))


@pytest.mark.asyncio
async def test_home_assistant_read_search_and_control() -> None:
    now = datetime.now(UTC)
    states = [
        SimpleNamespace(
            domain="light",
            entity_id="light.kitchen",
            state="on",
            attributes={"friendly_name": "Kitchen Light", "brightness": 128},
            last_changed=now,
            last_updated=now,
        ),
        SimpleNamespace(
            domain="switch",
            entity_id="switch.garage",
            state="off",
            attributes={},
            last_changed=now,
            last_updated=now,
        ),
    ]
    services = FakeServices()
    hass = SimpleNamespace(
        states=FakeStates(states),
        services=services,
        config=SimpleNamespace(version="2026.7", location_name="Home"),
        data={"area_registry": SimpleNamespace(areas={"one": {}, "two": {}})},
    )
    configured = registry(hass)
    overview = await configured._async_home_assistant("ha_get_overview", {})
    assert overview["entity_count"] == 2
    assert overview["areas"] == 2
    search = await configured._async_home_assistant(
        "ha_search", {"query": "light", "limit": 1}
    )
    assert search["results"] == [
        {"entity_id": "light.kitchen", "name": "Kitchen Light", "state": "on"}
    ]
    search = await configured._async_home_assistant("ha_search", {"query": "garage"})
    assert search["results"][0]["name"] is None
    assert (
        await configured._async_home_assistant(
            "ha_get_state", {"entity_id": "light.missing"}
        )
    )["error"]
    state = await configured._async_home_assistant(
        "ha_get_state", {"entity_id": "light.kitchen"}
    )
    assert state["attributes"]["brightness"] == 128
    with pytest.raises(ValueError, match="not allowlisted"):
        await configured._async_home_assistant(
            "ha_call_service", {"domain": "homeassistant", "service": "restart"}
        )
    controlled = await configured._async_home_assistant(
        "ha_call_service",
        {
            "domain": "light",
            "service": "turn_on",
            "entity_id": "light.kitchen",
            "service_data": {"brightness": 255},
        },
    )
    assert controlled["data"] == {
        "brightness": 255,
        "entity_id": "light.kitchen",
    }
    assert services.calls[0][-1] is True
    preserved = await configured._async_home_assistant(
        "ha_call_service",
        {
            "domain": "light",
            "service": "turn_off",
            "entity_id": "light.ignored",
            "service_data": {"entity_id": "light.kitchen"},
        },
    )
    assert preserved["data"]["entity_id"] == "light.kitchen"


@pytest.mark.asyncio
async def test_flight_tracker_overhead_and_bbox() -> None:
    near = [
        "abc123",
        " TEST1 ",
        "US",
        0,
        0,
        -121.5,
        38.5,
        1000,
        False,
        100,
        90,
        1,
        None,
        1000,
        "1200",
    ]
    far = [*near]
    far[5] = -100
    far[6] = 50
    short = ["too", "short"]
    configured = registry()
    configured._async_json = AsyncMock(
        side_effect=[{"states": [short, near, far]}, {"states": [near[:14]]}]
    )
    overhead = await configured._async_flight_tracker(
        "get_overhead_flights",
        {"latitude": 38.5, "longitude": -121.5, "radius_km": 10},
    )
    assert overhead["count"] == 1
    assert overhead["flights"][0]["distance_km"] == 0
    bbox = await configured._async_flight_tracker(
        "get_states_in_bbox",
        {"min_lat": 1, "max_lat": 2, "min_lon": 3, "max_lon": 4},
    )
    assert bbox["flights"][0]["squawk"] is None


@pytest.mark.asyncio
async def test_apple_calendar_listing_and_event_selection() -> None:
    configured = registry()
    calendars = [
        {"name": "Home", "url": "https://calendar.test/home"},
        {"name": "School", "url": "https://calendar.test/school"},
    ]
    configured._async_apple_calendars = AsyncMock(return_value=calendars)
    assert await configured._async_apple_calendar("calendar_list_calendars", {}) == {
        "calendars": calendars
    }
    configured._async_apple_events = AsyncMock(return_value=[{"summary": "Event"}])
    selected = await configured._async_apple_calendar(
        "calendar_get_events",
        {
            "calendar_url": calendars[0]["url"],
            "start_date": "2026-07-14T00:00:00Z",
            "end_date": "2026-07-15T00:00:00Z",
            "max_results": 1,
        },
    )
    assert selected == {"events": [{"summary": "Event"}]}
    configured._async_apple_events = AsyncMock(return_value=[])
    await configured._async_apple_calendar(
        "calendar_get_events", {"calendar_url": "missing", "days": 1}
    )
    assert configured._async_apple_events.await_count == 2


@pytest.mark.asyncio
async def test_caldav_request_success_and_error() -> None:
    session = FakeSession(FakeResponse(207, "<ok/>"), FakeResponse(401, "denied"))
    configured = registry()
    with patch(
        "custom_components.groq.simple_tools.async_get_clientsession",
        return_value=session,
    ):
        assert (
            await configured._async_caldav(
                "PROPFIND", "https://cal.test", "<body/>", depth="1"
            )
            == "<ok/>"
        )
        with pytest.raises(ValueError, match="CalDAV HTTP 401"):
            await configured._async_caldav("REPORT", "https://cal.test", "<body/>")
    assert session.calls[0][1]["headers"]["depth"] == "1"


@pytest.mark.asyncio
async def test_apple_calendar_discovery_and_report_parsing() -> None:
    configured = registry()
    principal = """<d:multistatus xmlns:d='DAV:'><d:response><d:propstat><d:prop><d:current-user-principal><d:href>/principal/</d:href></d:current-user-principal></d:prop></d:propstat></d:response></d:multistatus>"""
    home = """<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'><d:response><d:propstat><d:prop><c:calendar-home-set><d:href>/home/</d:href></c:calendar-home-set></d:prop></d:propstat></d:response></d:multistatus>"""
    listing = """<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'>
      <d:response><d:href>/home/</d:href><d:propstat><d:prop><d:resourcetype/></d:prop></d:propstat></d:response>
      <d:response><d:href>/home/main/</d:href><d:propstat><d:prop><d:displayname>Main</d:displayname><d:resourcetype><c:calendar/></d:resourcetype></d:prop></d:propstat></d:response>
      <d:response><d:propstat><d:prop><d:displayname>No href</d:displayname><d:resourcetype><c:calendar/></d:resourcetype></d:prop></d:propstat></d:response>
    </d:multistatus>"""
    configured._async_caldav = AsyncMock(side_effect=[principal, home, listing])
    calendars = await configured._async_apple_calendars()
    assert calendars == [
        {"name": "Main", "url": "https://caldav.icloud.com/home/main/"}
    ]

    report = """<d:multistatus xmlns:d='DAV:' xmlns:c='urn:ietf:params:xml:ns:caldav'><d:response><d:propstat><d:prop><c:calendar-data>BEGIN:VCALENDAR
BEGIN:VEVENT
UID:1
SUMMARY:Test
END:VEVENT
END:VCALENDAR</c:calendar-data><c:calendar-data /></d:prop></d:propstat></d:response></d:multistatus>"""
    configured._async_caldav = AsyncMock(return_value=report)
    events = await configured._async_apple_events(
        calendars[0]["url"],
        datetime(2026, 7, 14, tzinfo=UTC),
        datetime(2026, 7, 15, tzinfo=UTC),
    )
    assert events == [{"id": "1", "summary": "Test"}]


@pytest.mark.asyncio
async def test_google_workspace_tools() -> None:
    configured = registry()
    configured._async_json = AsyncMock(return_value={"ok": True})
    calendar = await configured._async_google_workspace(
        "google_get_calendar_events",
        {
            "calendar_id": "person@example.com",
            "start_date": "2026-07-14T00:00:00Z",
            "end_date": "2026-07-15T00:00:00Z",
            "max_results": 200,
        },
    )
    assert calendar == {"ok": True}
    await configured._async_google_workspace(
        "google_search_contacts", {"query": "Parker", "limit": 100}
    )

    configured._async_json = AsyncMock(
        side_effect=[{"messages": [{"id": "one"}]}, {"id": "one", "snippet": "Hi"}]
    )
    gmail = await configured._async_google_workspace(
        "google_search_emails", {"query": "newer_than:1d", "detail_limit": 1}
    )
    assert gmail["details"][0]["snippet"] == "Hi"

    for name, args in (
        ("google_list_task_lists", {}),
        ("google_list_tasks", {"show_completed": True, "max_results": 200}),
        ("google_create_task", {"title": "Test", "notes": "Note"}),
    ):
        configured._async_json = AsyncMock(return_value={"tool": name})
        assert (await configured._async_google_workspace(name, args))["tool"] == name

    configured._async_json = AsyncMock(side_effect=[{"id": "task"}, {"id": "task"}])
    completed = await configured._async_google_workspace(
        "google_complete_task", {"task_id": "task", "task_list_id": "list"}
    )
    assert completed["id"] == "task"
    payload = configured._async_json.await_args.kwargs["payload"]
    assert payload["status"] == "completed"
    assert payload["completed"]


@pytest.mark.asyncio
async def test_spotify_read_search_and_playback_tools() -> None:
    configured = registry()
    configured._async_json = AsyncMock(return_value={"ok": True})
    await configured._async_spotify(
        "spotify_search", {"query": "song", "type": "track", "limit": 100}
    )
    for name in (
        "spotify_get_now_playing",
        "spotify_get_playlists",
        "spotify_get_playlist_tracks",
        "spotify_get_recently_played",
        "spotify_get_saved_tracks",
        "spotify_get_queue",
        "spotify_get_devices",
    ):
        await configured._async_spotify(name, {"playlistId": "playlist"})
    await configured._async_spotify("spotify_pause", {"deviceId": "device"})
    await configured._async_spotify("spotify_resume", {})
    await configured._async_spotify("spotify_play", {})
    await configured._async_spotify("spotify_play", {"type": "track", "id": "track"})
    assert configured._async_json.await_args.kwargs["payload"] == {
        "uris": ["spotify:track:track"]
    }
    await configured._async_spotify(
        "spotify_play", {"uri": "spotify:playlist:playlist"}
    )
    assert configured._async_json.await_args.kwargs["payload"] == {
        "context_uri": "spotify:playlist:playlist"
    }
    await configured._async_spotify("spotify_skip_next", {})
    await configured._async_spotify("spotify_skip_previous", {})
    await configured._async_spotify(
        "spotify_add_to_queue", {"type": "track", "id": "track"}
    )
    await configured._async_spotify("spotify_set_volume", {"volumePercent": 150})
    assert configured._async_json.await_args.kwargs["params"]["volume_percent"] == 100

    configured._async_json = AsyncMock(
        side_effect=[{"device": {"volume_percent": 40}}, {"ok": True}]
    )
    await configured._async_spotify("spotify_adjust_volume", {"adjustment": -10})
    assert configured._async_json.await_args.kwargs["params"]["volume_percent"] == 30


@pytest.mark.asyncio
async def test_openroute_tools() -> None:
    configured = registry()
    configured._async_json = AsyncMock(return_value={"features": []})
    assert await configured._async_openroute(
        "openroute_geocode", {"location": "Sacramento"}
    ) == {"features": []}
    assert await configured._async_openroute(
        "openroute_reverse_geocode", {"lon": -121.5, "lat": 38.5}
    ) == {"features": []}


def test_simple_tool_helpers() -> None:
    assert _distance_km(38.5, -121.5, 38.5, -121.5) == 0
    assert _parse_date(None) is None
    assert _parse_date("invalid") is None
    assert _parse_date("2026-07-14T12:00:00").tzinfo == UTC
    assert _parse_date("2026-07-14T12:00:00Z").tzinfo == UTC
    xml = "<root><current-user-principal><href>/principal/</href></current-user-principal></root>"
    assert _xml_href(xml, "current-user-principal") == "/principal/"
    assert _xml_href("<root><other /></root>", "missing") is None
    ics = r"""BEGIN:VEVENT
UID:1
SUMMARY:Test\, Event
DESCRIPTION:First\n second
UNKNOWN:value
bad line
END:VEVENT
BEGIN:VEVENT
UNKNOWN:value
END:VEVENT"""
    assert _parse_ics_events(ics) == [
        {"id": "1", "summary": "Test, Event", "description": "First\n second"}
    ]
