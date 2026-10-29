"""Typed errors with stable codes and CLI exit codes (LLD §5.3, §14.1)."""

from __future__ import annotations

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_DATABASE = 3
EXIT_PARTIAL = 4
EXIT_DEPENDENCY = 5


class RadarError(Exception):
    code = "radar_error"
    exit_code = EXIT_FAILURE


class ConfigurationError(RadarError):
    code = "configuration_error"
    exit_code = EXIT_USAGE


class DatabaseInitializationError(RadarError):
    code = "database_initialization_error"
    exit_code = EXIT_DATABASE


class MigrationIntegrityError(RadarError):
    code = "migration_integrity_error"
    exit_code = EXIT_DATABASE
