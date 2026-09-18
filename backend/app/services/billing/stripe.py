"""Small Stripe HTTP client; price and ownership are always supplied by the server."""

from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from app.config import Settings


class StripeClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def post(self, path: str, values: dict[str, str]):
        secret = self.settings.stripe_secret_key.get_secret_value()
        if not secret:
            raise HTTPException(503, "Billing is not configured")
        try:
            response = httpx.post(
                f"https://api.stripe.com/v1/{path}",
                headers={
                    "Authorization": f"Bearer {secret}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                content=urlencode(values),
                timeout=15,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(502, "Billing provider is temporarily unavailable") from exc
        if response.status_code >= 400:
            raise HTTPException(502, "Billing provider rejected the request")
        return response.json()

    def create_customer(self, user):
        return self.post("customers", {"email": user.email, "metadata[app_user_id]": str(user.id)})

    def create_checkout(self, user):
        s = self.settings
        if not s.stripe_pro_price_id:
            raise HTTPException(503, "Billing is not configured")
        return self.post(
            "checkout/sessions",
            {
                "mode": "subscription",
                "customer": user.stripe_customer_id,
                "client_reference_id": str(user.id),
                "line_items[0][price]": s.stripe_pro_price_id,
                "line_items[0][quantity]": "1",
                "success_url": s.stripe_success_url,
                "cancel_url": s.stripe_cancel_url,
                "subscription_data[metadata][app_user_id]": str(user.id),
            },
        )

    def create_portal(self, user):
        return self.post(
            "billing_portal/sessions",
            {
                "customer": user.stripe_customer_id,
                "return_url": self.settings.stripe_portal_return_url,
            },
        )
