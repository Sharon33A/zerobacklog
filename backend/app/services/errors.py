"""Upload-domain error types."""


class UploadValidationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DuplicateUploadError(Exception):
    def __init__(self, existing_upload_id: str | None) -> None:
        super().__init__("This file has already been uploaded.")
        self.existing_upload_id = existing_upload_id


class InfrastructureError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ResourceNotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("The requested resource was not found.")
        self.code = "resource_not_found"
        self.message = "The requested resource was not found."


class ResourceActionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class UrlValidationError(ResourceActionError):
    """A public-link input or network-boundary validation failure."""
