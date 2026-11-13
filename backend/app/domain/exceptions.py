class DomainError(Exception):
    """Base class for expected domain failures."""


class NotFoundError(DomainError):
    pass


class BadRequestError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class IllegalTransition(ConflictError):
    def __init__(self, current: str, target: str) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Illegal order transition: {current} -> {target}")
