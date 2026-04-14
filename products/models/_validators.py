from django.core.validators import FileExtensionValidator

_image_ext_validator = FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "gif", "webp"])
_document_ext_validator = FileExtensionValidator(
    allowed_extensions=["pdf", "xlsx", "xls", "csv", "txt", "docx", "jpg", "jpeg", "png"]
)
_excel_ext_validator = FileExtensionValidator(allowed_extensions=["xlsx", "xls", "csv"])
