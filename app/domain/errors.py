class DomainError(Exception):
    pass


class NotFoundError(DomainError):
    pass


class NoSuitableLegError(DomainError):
    pass


class InsufficientTokensError(DomainError):
    pass


class TooManyActiveTasksError(DomainError):
    pass
