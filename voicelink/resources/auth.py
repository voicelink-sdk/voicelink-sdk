"""Auth — session and credential actions for the authenticated user."""

from __future__ import annotations

from typing import Any

from .base import Resource


class AuthResource(Resource):
    def logout(self) -> dict[str, Any]:
        """Log out the current session."""
        return self._transport.request("POST", "/v1/auth/logout")

    def me(self) -> dict[str, Any]:
        """Get the authenticated user's profile."""
        return self._transport.request("GET", "/v1/auth/user")

    def forgot_password(self, *, email: str) -> dict[str, Any]:
        """Request a password-reset email."""
        body = self._clean({"email": email})
        return self._transport.request("POST", "/v1/auth/forgot-password", json=body)

    def reset_password(
        self,
        *,
        token: str,
        email: str,
        password: str,
        password_confirmation: str,
    ) -> dict[str, Any]:
        """Reset the password using a reset token."""
        body = self._clean(
            {
                "token": token,
                "email": email,
                "password": password,
                "password_confirmation": password_confirmation,
            }
        )
        return self._transport.request("POST", "/v1/auth/reset-password", json=body)

    def verify_otp(self, *, username: str, otp: str) -> dict[str, Any]:
        """Verify a one-time passcode."""
        body = self._clean({"username": username, "otp": otp})
        return self._transport.request("POST", "/v1/auth/verify-otp", json=body)

    def resend_otp(self, *, username: str) -> dict[str, Any]:
        """Resend a one-time passcode."""
        body = self._clean({"username": username})
        return self._transport.request("POST", "/v1/auth/resend-otp", json=body)
