"""Control-plane resources — one module per kind of thing you manage."""

from .agents import AgentsResource
from .auth import AuthResource
from .call_logs import CallLogsResource
from .call_settings import CallSettingsResource
from .calls import CallsResource
from .clients import ClientsResource
from .dids import DidsResource
from .kyc import KycResource
from .payments import PaymentsResource
from .purchase import PurchaseResource
from .renewals import RenewalsResource
from .reseller import ResellerResource
from .routing import CallRoutingResource
from .sip_trunks import SipTrunksResource
from .sounds import SoundsResource
from .sub_users import SubUsersResource
from .time_settings import TimeSettingsResource
from .websocket_bots import WebSocketBotsResource
from .websocket_management import WebsocketManagementResource
from .websocket_time_groups import WebsocketTimeGroupsResource

__all__ = [
    "AgentsResource",
    "AuthResource",
    "CallLogsResource",
    "CallRoutingResource",
    "CallSettingsResource",
    "CallsResource",
    "ClientsResource",
    "DidsResource",
    "KycResource",
    "PaymentsResource",
    "PurchaseResource",
    "RenewalsResource",
    "ResellerResource",
    "SipTrunksResource",
    "SoundsResource",
    "SubUsersResource",
    "TimeSettingsResource",
    "WebSocketBotsResource",
    "WebsocketManagementResource",
    "WebsocketTimeGroupsResource",
]
