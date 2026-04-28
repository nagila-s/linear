class AppError(Exception):
    """Base error for predictable application failures."""


class ValidationError(AppError):
    """Input validation or business rule violation."""


class IntegrationError(AppError):
    """Failure while calling external integrations."""


class PersistenceError(AppError):
    """Failure while persisting or retrieving state."""
