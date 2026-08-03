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
