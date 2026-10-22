import uuid
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.domain.enums import ErrorType


@dataclass(frozen=True)
class Submission:
    provider: str
    client_ref: uuid.UUID
    prompt: str
    ref_images: list[str]


class ProviderError(Exception):
    def __init__(self, error_type: ErrorType, detail: str) -> None:
        super().__init__(detail)
        self.error_type = error_type
        self.detail = detail


class ProviderGateway(Protocol):
    async def submit(self, submission: Submission) -> str: ...

    async def aclose(self) -> None: ...


class HttpProviderGateway:
    def __init__(self, urls: dict[str, str], callback_base_url: str, timeout: float) -> None:
        self._urls = urls
        self._callback_base_url = callback_base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=timeout)

    async def submit(self, submission: Submission) -> str:
        base_url = self._urls.get(submission.provider)
        if base_url is None:
            raise ProviderError(ErrorType.TECHNICAL, f"provider {submission.provider} is not configured")
        payload = {
            "prompt": submission.prompt,
            "ref_images": submission.ref_images,
            "client_ref": str(submission.client_ref),
            "callback_url": f"{self._callback_base_url}/webhooks/providers/{submission.provider}",
        }
        try:
            response = await self._http.post(f"{base_url.rstrip('/')}/tasks", json=payload)
        except httpx.TimeoutException:
            raise ProviderError(ErrorType.TECHNICAL, "timeout on POST /tasks") from None
        except httpx.HTTPError as exc:
            raise ProviderError(ErrorType.TECHNICAL, f"transport error: {exc!r}") from None
        if response.status_code >= 500 or response.status_code == 429:
            raise ProviderError(ErrorType.TECHNICAL, f"HTTP {response.status_code} on POST /tasks")
        if response.status_code >= 400:
            raise ProviderError(ErrorType.PAYLOAD, f"HTTP {response.status_code} on POST /tasks")
        try:
            return str(response.json()["external_id"])
        except (ValueError, KeyError, TypeError):
            raise ProviderError(ErrorType.TECHNICAL, "malformed response on POST /tasks") from None

    async def aclose(self) -> None:
        await self._http.aclose()
