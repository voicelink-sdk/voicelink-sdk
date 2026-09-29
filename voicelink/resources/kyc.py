"""KYC — reseller KYC onboarding (mostly pre-integration)."""

from __future__ import annotations

from typing import Any

from .base import Resource


class KycResource(Resource):
    def status(self) -> dict[str, Any]:
        """Get the current KYC status."""
        return self._transport.request("GET", "/v1/reseller/kyc/status")

    def step1_register(
        self,
        *,
        term_and_condition: str,
        account_type: str,
        full_name: str,
        phone: str,
        billing_address: str,
        state: str,
        city: str,
        pincode: str,
        client_id: int | None = None,
        business_name: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        """Step 1 — register details."""
        body = self._clean(
            {
                "term_and_condition": term_and_condition,
                "account_type": account_type,
                "full_name": full_name,
                "phone": phone,
                "billing_address": billing_address,
                "state": state,
                "city": city,
                "pincode": pincode,
                "client_id": client_id,
                "business_name": business_name,
                "email": email,
            }
        )
        return self._transport.request(
            "POST", "/v1/reseller/kyc/step-1-register-details", json=body
        )

    def step2_pan(
        self,
        *,
        pan_holder_name: str,
        pan_number: str,
        client_id: int | None = None,
    ) -> dict[str, Any]:
        """Step 2 — verify PAN."""
        body = self._clean(
            {
                "pan_holder_name": pan_holder_name,
                "pan_number": pan_number,
                "client_id": client_id,
            }
        )
        return self._transport.request("POST", "/v1/reseller/kyc/step-2-pan-verify", json=body)

    def step3_aadhaar_init(
        self,
        *,
        client_id: int | None = None,
        redirect_url: str | None = None,
    ) -> dict[str, Any]:
        """Step 3 — start Aadhaar verification."""
        body = self._clean(
            {
                "client_id": client_id,
                "redirect_url": redirect_url,
            }
        )
        return self._transport.request("POST", "/v1/reseller/kyc/step-3-aadhaar-init", json=body)

    def step3_aadhaar_callback(self, *, uid: str | None = None) -> dict[str, Any]:
        """Step 3 — Aadhaar verification callback."""
        params = self._clean({"uid": uid})
        return self._transport.request(
            "GET", "/v1/reseller/kyc/step-3-aadhaar-callback", params=params
        )

    def step4_gst(
        self,
        *,
        gst_number: str,
        client_id: int | None = None,
    ) -> dict[str, Any]:
        """Step 4 — verify GST."""
        body = self._clean(
            {
                "gst_number": gst_number,
                "client_id": client_id,
            }
        )
        return self._transport.request("POST", "/v1/reseller/kyc/step-4-gst-verify", json=body)

    def final_submit(self) -> dict[str, Any]:
        """Submit the completed KYC."""
        return self._transport.request("POST", "/v1/reseller/kyc/final-submit")
