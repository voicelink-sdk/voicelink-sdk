"""Transport behavior: envelope unwrapping and HTTP → typed-error mapping."""

import httpx
import pytest
import respx

from voicelink._transport import Transport
from voicelink.errors import (
    NotFoundError,
    ValidationError,
    VoiceLinkAPIError,
    VoiceLinkConnectionError,
)

BASE = "https://api.test/api"


def _transport(**kw) -> Transport:
    return Transport(BASE, "tok", max_retries=0, **kw)


@respx.mock
def test_unwraps_data_envelope():
    respx.get(f"{BASE}/v1/thing").mock(
        return_value=httpx.Response(200, json={"status": True, "message": "ok", "data": {"id": 7}})
    )
    with _transport() as t:
        assert t.request("GET", "/v1/thing") == {"id": 7}


@respx.mock
def test_sends_bearer_token():
    route = respx.get(f"{BASE}/v1/thing").mock(
        return_value=httpx.Response(200, json={"status": True, "data": []})
    )
    with _transport() as t:
        t.request("GET", "/v1/thing")
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"


@respx.mock
def test_logical_failure_raises_even_on_200():
    respx.get(f"{BASE}/v1/thing").mock(
        return_value=httpx.Response(200, json={"status": False, "message": "nope"})
    )
    with _transport() as t, pytest.raises(VoiceLinkAPIError) as exc:
        t.request("GET", "/v1/thing")
    assert "nope" in str(exc.value)


@respx.mock
def test_404_maps_to_not_found():
    respx.get(f"{BASE}/v1/missing").mock(
        return_value=httpx.Response(404, json={"message": "not here"})
    )
    with _transport() as t, pytest.raises(NotFoundError):
        t.request("GET", "/v1/missing")


@respx.mock
def test_422_maps_to_validation_error_with_fields():
    respx.post(f"{BASE}/v1/thing").mock(
        return_value=httpx.Response(
            422, json={"message": "invalid", "errors": {"bot_name": ["required"]}}
        )
    )
    with _transport() as t, pytest.raises(ValidationError) as exc:
        t.request("POST", "/v1/thing", json={})
    assert exc.value.errors == {"bot_name": ["required"]}


@respx.mock
def test_none_params_are_dropped():
    route = respx.get(f"{BASE}/v1/thing").mock(
        return_value=httpx.Response(200, json={"status": True, "data": []})
    )
    with _transport() as t:
        t.request("GET", "/v1/thing", params={"a": 1, "b": None})
    assert "b" not in route.calls.last.request.url.params
    assert route.calls.last.request.url.params["a"] == "1"


@respx.mock
def test_connection_error_wrapped():
    respx.get(f"{BASE}/v1/thing").mock(side_effect=httpx.ConnectError("boom"))
    with _transport() as t, pytest.raises(VoiceLinkConnectionError):
        t.request("GET", "/v1/thing")
