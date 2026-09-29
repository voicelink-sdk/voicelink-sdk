"""The account-administration resources send the right method, path, and body."""

import json

import httpx
import respx

from voicelink import VoiceLinkClient
from voicelink.enums import Status

BASE = "https://api.test/api"


def _client() -> VoiceLinkClient:
    return VoiceLinkClient("tok", base_url=BASE, client_id=123, max_retries=0)


def _ok(data):
    return httpx.Response(200, json={"status": True, "data": data})


@respx.mock
def test_agents_create_sends_body():
    route = respx.post(f"{BASE}/v1/agent/create").mock(return_value=_ok({"id": 7}))
    with _client() as c:
        c.agents.create(first_name="Ada", last_name="L", phone_number="9111111111")
    body = json.loads(route.calls.last.request.content)
    assert body["first_name"] == "Ada"
    assert body["phone_number"] == "9111111111"
    assert body["status"] == 1  # Status.ACTIVE default


@respx.mock
def test_agents_list_returns_page():
    respx.get(f"{BASE}/v1/agent/list").mock(
        return_value=_ok(
            {"data": [{"id": 1}, {"id": 2}], "current_page": 1, "total": 2, "last_page": 1}
        )
    )
    with _client() as c:
        page = c.agents.list(search="a")
    assert len(page) == 2
    assert page.total == 2


@respx.mock
def test_sub_users_create_and_sync_permissions():
    respx.post(f"{BASE}/v1/sub-user").mock(return_value=_ok({"id": 3}))
    perm = respx.post(f"{BASE}/v1/sub-user/3/permissions").mock(return_value=_ok({"ok": True}))
    with _client() as c:
        c.sub_users.create(name="Ops", email="o@x.com", password="pw", permissions=["calls.read"])
        c.sub_users.sync_permissions(3, permissions=["calls.read", "calls.write"])
    body = json.loads(perm.calls.last.request.content)
    assert body["permissions"] == ["calls.read", "calls.write"]


@respx.mock
def test_clients_create_and_allocate_wallet():
    respx.post(f"{BASE}/v1/reseller/client/create").mock(return_value=_ok({"id": 9}))
    alloc = respx.post(f"{BASE}/v1/reseller/client/allocate-wallet/9").mock(
        return_value=_ok({"ok": 1})
    )
    with _client() as c:
        c.clients.create(
            first_name="A",
            last_name="B",
            username="ab",
            email="a@b.com",
            password="pw",
            channel_count=2,
        )
        c.clients.allocate_wallet(9, amount=100.0, description="topup")
    body = json.loads(alloc.calls.last.request.content)
    assert body["amount"] == 100.0
    assert body["description"] == "topup"


@respx.mock
def test_kyc_step2_pan_body():
    route = respx.post(f"{BASE}/v1/reseller/kyc/step-2-pan-verify").mock(
        return_value=_ok({"ok": 1})
    )
    with _client() as c:
        c.kyc.step2_pan(pan_holder_name="Ada L", pan_number="ABCDE1234F")
    body = json.loads(route.calls.last.request.content)
    assert body["pan_number"] == "ABCDE1234F"
    assert "client_id" not in body  # None dropped by _clean


@respx.mock
def test_purchase_available_dids_sends_type_param():
    route = respx.get(f"{BASE}/v1/reseller/purchase/dids").mock(
        return_value=_ok({"data": [], "current_page": 1, "total": 0, "last_page": 1})
    )
    with _client() as c:
        c.purchase.available_dids(country_code="91", did_type="mobile", months=12)
    q = dict(route.calls.last.request.url.params)
    assert q["type"] == "mobile"  # did_type sent under key "type"
    assert q["country_code"] == "91"
    assert q["months"] == "12"


@respx.mock
def test_purchase_lock_did_body():
    route = respx.post(f"{BASE}/v1/reseller/purchase/lock-did").mock(
        return_value=_ok({"order_id": 5})
    )
    with _client() as c:
        c.purchase.lock_did(months=6, did_ids=[11, 12])
    body = json.loads(route.calls.last.request.content)
    assert body["did_ids"] == [11, 12]
    assert body["months"] == 6


@respx.mock
def test_dids_release_body():
    route = respx.post(f"{BASE}/v1/reseller/did/release").mock(return_value=_ok({"ok": 1}))
    with _client() as c:
        c.dids.release("919484950416")
    body = json.loads(route.calls.last.request.content)
    assert body["did_number"] == "919484950416"


@respx.mock
def test_call_logs_details_sends_call_id():
    route = respx.get(f"{BASE}/v1/call-log/details").mock(return_value=_ok({"id": "abc"}))
    with _client() as c:
        c.call_logs.details("abc")
    assert dict(route.calls.last.request.url.params)["call_id"] == "abc"


@respx.mock
def test_payments_update_wraps_data():
    route = respx.post(f"{BASE}/v1/update-payments").mock(return_value=_ok({"ok": 1}))
    with _client() as c:
        c.payments.update_payments([{"invoice": "INV-1"}])
    body = json.loads(route.calls.last.request.content)
    assert body["data"] == [{"invoice": "INV-1"}]


@respx.mock
def test_auth_me_hits_user_endpoint():
    route = respx.get(f"{BASE}/v1/auth/user").mock(return_value=_ok({"id": 1, "username": "u"}))
    with _client() as c:
        user = c.auth.me()
    assert route.called
    assert user["username"] == "u"


@respx.mock
def test_time_settings_create_sends_schedule():
    route = respx.post(f"{BASE}/v1/time-setting/create").mock(return_value=_ok({"id": 1}))
    with _client() as c:
        c.time_settings.create(
            group_name="Business hours",
            schedule=[{"day": "mon", "from": "09:00", "to": "18:00"}],
            status=Status.ACTIVE,
        )
    body = json.loads(route.calls.last.request.content)
    assert body["group_name"] == "Business hours"
    assert body["status"] == 1
    assert body["schedule"][0]["day"] == "mon"


@respx.mock
def test_sounds_create_passthrough():
    route = respx.post(f"{BASE}/v1/sound/create").mock(return_value=_ok({"id": 1}))
    with _client() as c:
        c.sounds.create(name="welcome", type="welcome")
    body = json.loads(route.calls.last.request.content)
    assert body["name"] == "welcome"
    assert body["type"] == "welcome"
