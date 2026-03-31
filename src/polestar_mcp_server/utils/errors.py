"""
Custom exception hierarchy for the Polestar MCP Server.
"""


class PolestarMCPError(Exception):
    """Base exception for all Polestar MCP errors."""

    def __init__(self, message: str, error_code: str = "UNKNOWN_ERROR", details: dict | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


class AuthenticationError(PolestarMCPError):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Authentication failed", details: dict | None = None):
        super().__init__(message, error_code="AUTH_ERROR", details=details)


class APIError(PolestarMCPError):
    """Raised when the Polestar API returns an error."""

    def __init__(self, message: str, status_code: int | None = None, details: dict | None = None):
        super().__init__(message, error_code="API_ERROR", details=details)
        self.status_code = status_code


class RateLimitError(PolestarMCPError):
    """Raised when API rate limit is hit."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: int | None = None):
        super().__init__(message, error_code="RATE_LIMIT_ERROR")
        self.retry_after = retry_after


class ConfigurationError(PolestarMCPError):
    """Raised when configuration is invalid or missing."""

    def __init__(self, message: str = "Configuration error", details: dict | None = None):
        super().__init__(message, error_code="CONFIG_ERROR", details=details)


class VehicleNotFoundError(PolestarMCPError):
    """Raised when the requested vehicle VIN is not found."""

    def __init__(self, vin: str):
        super().__init__(
            f"Vehicle with VIN '{vin}' not found in your account.",
            error_code="VEHICLE_NOT_FOUND",
            details={"vin": vin},
        )
