from __future__ import annotations

from dataclasses import asdict
import base64
import json

import requests

from elsaflow.models import X402PaymentRecord, new_id


class X402ClientWrapper:
    def __init__(self, base_signer) -> None:
        self.signer = base_signer

    def get_json(self, db, session_id: str, url: str, timeout: int = 10) -> tuple[dict | None, X402PaymentRecord | None]:
        response = requests.get(url, timeout=timeout)
        if response.status_code != 402:
            return response.json(), None

        encoded = response.headers.get("PAYMENT-REQUIRED", "")
        try:
            decoded = json.loads(base64.b64decode(encoded).decode("utf-8")) if encoded else {}
        except Exception:
            decoded = {}

        payment_payload = {
            "resource": url,
            "network": decoded.get("network", "eip155:8453"),
            "amount": decoded.get("amount", "0"),
            "payTo": decoded.get("payTo", ""),
        }
        signature = self.signer.sign_message(json.dumps(payment_payload, sort_keys=True))
        retry = requests.get(
            url,
            timeout=timeout,
            headers={"PAYMENT-SIGNATURE": base64.b64encode(json.dumps({"signature": signature}).encode("utf-8")).decode("utf-8")},
        )
        payment = X402PaymentRecord(
            payment_id=new_id("pay"),
            resource_url=url,
            status="SETTLED" if retry.ok else "FAILED",
            amount=str(decoded.get("amount", "0")),
            network=str(decoded.get("network", "eip155:8453")),
            pay_to=str(decoded.get("payTo", "")),
            scheme=str(decoded.get("scheme", "exact")),
            response_code=retry.status_code,
            settlement_response=retry.text[:1000],
        )
        db.insert_payload("x402_payments", session_id, asdict(payment), key="payment_id")
        return retry.json() if retry.ok else None, payment
