"""Typed errors with stable codes and CLI exit codes (LLD §5.3, §14.1)."""

from __future__ import annotations

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_DATABASE = 3
EXIT_PARTIAL = 4
EXIT_DEPENDENCY = 5


class OhgError(Exception):
    code = "ohg_error"
    exit_code = EXIT_FAILURE


class ConfigurationError(OhgError):
    code = "configuration_error"
    exit_code = EXIT_USAGE


class DatabaseInitializationError(OhgError):
    code = "database_initialization_error"
    exit_code = EXIT_DATABASE


class MigrationIntegrityError(OhgError):
    code = "migration_integrity_error"
    exit_code = EXIT_DATABASE


class SourcePolicyDenied(OhgError):
    """URL, redirect, robots or scope rule forbids fetching. Not counted as a source failure."""

    code = "source_policy_denied"


class FetchError(OhgError):
    code = "fetch_error"

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        retry_after: float | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.retry_after = retry_after
        self.retryable = retryable


class FetchTimeout(FetchError):
    code = "fetch_timeout"


class FetchNetworkError(FetchError):
    code = "network_error"


class FetchHTTPError(FetchError):
    code = "http_error"


class ContentTooLarge(FetchError):
    code = "content_too_large"


class UnsupportedContentType(FetchError):
    code = "unsupported_content_type"


class ParseError(OhgError):
    code = "parse_error"


class LLMUnavailable(OhgError):
    """Gateway down, quota exhausted, acknowledgement missing or LLM disabled. Work is queued;
    deterministic processing continues and no other provider is ever tried."""

    code = "llm_unavailable"


class LLMInvalidResponse(OhgError):
    code = "llm_invalid_response"
