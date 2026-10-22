from app.clients.providers import ProviderError, Submission
from app.domain.enums import ErrorType


class FakeGateway:
    def __init__(self) -> None:
        self.submissions: list[Submission] = []
        self._errors: dict[str, ProviderError] = {}

    def reject(self, provider: str, error_type: ErrorType = ErrorType.TECHNICAL, detail: str = "HTTP 503") -> None:
        self._errors[provider] = ProviderError(error_type, detail)

    async def submit(self, submission: Submission) -> str:
        self.submissions.append(submission)
        if submission.provider in self._errors:
            raise self._errors[submission.provider]
        return f"{submission.provider}-{submission.client_ref.hex[:12]}"

    async def aclose(self) -> None:
        pass
