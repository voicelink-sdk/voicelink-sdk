"""Reseller — the reseller account's own profile and pre-auth signup."""

from __future__ import annotations

from typing import Any

from .base import Resource


class ResellerResource(Resource):
    def profile(self) -> dict[str, Any]:
        """Get the reseller's profile."""
        return self._transport.request("GET", "/v1/reseller/profile")

    def signup(
        self,
        *,
        first_name: str,
        last_name: str,
        company_name: str,
        email: str,
        username: str,
        phone: str,
        currency_code: str,
        password: str,
        password_confirmation: str,
    ) -> dict[str, Any]:
        """Sign up a new reseller. This endpoint is pre-authentication."""
        body = self._clean(
            {
                "first_name": first_name,
                "last_name": last_name,
                "company_name": company_name,
                "email": email,
                "username": username,
                "phone": phone,
                "currency_code": currency_code,
                "password": password,
                "password_confirmation": password_confirmation,
            }
        )
        return self._transport.request("POST", "/v1/reseller/signup", json=body)
