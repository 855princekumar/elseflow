from __future__ import annotations

from abc import ABC, abstractmethod
from hashlib import sha256

from elsaflow.models import SignerConfig


class AgentSigner(ABC):
    def __init__(self, config: SignerConfig) -> None:
        self.config = config

    @abstractmethod
    def sign_message(self, message: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def can_sign(self) -> bool:
        raise NotImplementedError


class DryRunSigner(AgentSigner):
    def sign_message(self, message: str) -> str:
        return f"dryrun_{sha256(message.encode('utf-8')).hexdigest()[:32]}"

    def can_sign(self) -> bool:
        return True


class LocalKeyReferenceSigner(AgentSigner):
    def sign_message(self, message: str) -> str:
        if not self.config.enabled or not self.config.key_reference:
            raise ValueError("Signer is not enabled or key reference is missing")
        seed = f"{self.config.key_reference}:{message}"
        return f"sig_{sha256(seed.encode('utf-8')).hexdigest()[:48]}"

    def can_sign(self) -> bool:
        return bool(self.config.enabled and self.config.key_reference)


def build_signer(config: SignerConfig) -> AgentSigner:
    if config.signer_type == "local-key-ref":
        return LocalKeyReferenceSigner(config)
    return DryRunSigner(config)
