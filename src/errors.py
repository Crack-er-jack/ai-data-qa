"""User-facing application errors."""


class AppError(Exception):
    """Recoverable product error with a message safe to show in the UI."""


class FileValidationError(AppError):
    pass


class IngestionError(AppError):
    pass


class SqlValidationError(AppError):
    pass


class QueryExecutionError(AppError):
    pass


class LlmError(AppError):
    pass
