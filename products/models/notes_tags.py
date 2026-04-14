# pylint: disable=broad-exception-caught,missing-class-docstring,no-member
from products.models._validators import _document_ext_validator

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import models


class NoteTag(models.Model):
    """Tags for categorizing notes. Scoped per Business Unit so each BU has its own tag library."""

    TAG_COLORS = [
        ("#3b82f6", "Blue"),
        ("#059669", "Green"),
        ("#d97706", "Amber"),
        ("#dc2626", "Red"),
        ("#0044CC", "Dark Blue"),
        ("#0891b2", "Cyan"),
        ("#0B5FFF", "Royal Blue"),
        ("#4b5563", "Gray"),
        ("#b8860b", "Bronze"),
        ("#65a30d", "Lime"),
    ]
    name = models.CharField(max_length=50)
    color = models.CharField(
        max_length=7, choices=TAG_COLORS, default="#3b82f6", help_text="Hex color code for the tag badge"
    )
    business_unit = models.ForeignKey(
        "BusinessUnit",
        on_delete=models.CASCADE,
        related_name="note_tags",
        null=True,
        blank=True,
        help_text="Tags are scoped to a Business Unit",
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        unique_together = ("name", "business_unit")

    def __str__(self):
        return self.name


class Note(models.Model):
    VISIBILITY_CHOICES = [
        ("public", "Public"),
        ("private", "Private"),
        ("stream", "Stream Only"),
    ]
    title = models.CharField(max_length=255)
    content = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="created_notes", on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="updated_notes", on_delete=models.SET_NULL, null=True
    )
    updated_at = models.DateTimeField(auto_now=True)
    is_public = models.BooleanField(default=True)
    visibility = models.CharField(
        max_length=10,
        choices=VISIBILITY_CHOICES,
        default="public",
        help_text=(
            "Public: visible to all BU users. Private: only you."
            " Stream: only users with access to the selected stream."
        ),
    )
    stream = models.ForeignKey(
        "Stream",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notes",
        help_text="Required when visibility is 'Stream Only'. Only users with access to this stream can view the note.",
    )
    tags = models.ManyToManyField(  # type: ignore[var-annotated]
        "NoteTag", blank=True, related_name="notes", help_text="Tags for categorizing and filtering notes"
    )
    business_unit = models.ForeignKey(
        "BusinessUnit",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="bu_notes",
        help_text="Business Unit this note belongs to",
    )

    def delete(self, *args, **kwargs):
        """Override delete to also remove all attachment files from storage"""
        attachments = self.attachments.all()
        for attachment in attachments:
            if attachment.file:
                try:
                    default_storage.delete(attachment.file.name)
                except Exception as e:
                    # Log the error but continue with deletion
                    print(f"Error deleting file {attachment.file.name}: {e}")
        super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.title} by {self.created_by.username}"

    class Meta:
        ordering = ["-created_at"]


class NoteAttachment(models.Model):
    note = models.ForeignKey("Note", related_name="attachments", on_delete=models.CASCADE)
    file = models.FileField(upload_to="note_attachments/", validators=[_document_ext_validator])
    original_filename = models.CharField(max_length=255)
    file_size = models.IntegerField()
    content_type = models.CharField(max_length=100)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    FILE_TYPE_CHOICES = [
        ("image", "Image"),
        ("document", "Document"),
        ("spreadsheet", "Spreadsheet"),
        ("pdf", "PDF"),
        ("other", "Other"),
    ]
    file_type = models.CharField(max_length=20, choices=FILE_TYPE_CHOICES, default="other")

    def save(self, *args, **kwargs):
        if self.file:
            self.file_size = self.file.size

            if self.content_type.startswith("image/"):
                self.file_type = "image"
            elif self.content_type in ["application/pdf"]:
                self.file_type = "pdf"
            elif self.content_type in [
                "application/vnd.ms-excel",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ]:
                self.file_type = "spreadsheet"
            elif self.content_type in [
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ]:
                self.file_type = "document"
            else:
                self.file_type = "other"

        super().save(*args, **kwargs)

    def get_file_icon(self):
        """Return appropriate FontAwesome icon based on file type"""
        icons = {
            "image": "fas fa-image",
            "document": "fas fa-file-word",
            "spreadsheet": "fas fa-file-excel",
            "pdf": "fas fa-file-pdf",
            "other": "fas fa-file",
        }
        return icons.get(self.file_type, "fas fa-file")

    def get_formatted_size(self):
        """Return human-readable file size"""
        size = self.file_size
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def delete(self, *args, **kwargs):
        """Override delete to also remove the file from storage"""
        if self.file:
            try:
                default_storage.delete(self.file.name)
            except Exception as e:
                # Log the error but continue with deletion
                print(f"Error deleting file {self.file.name}: {e}")
        super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.original_filename} - {self.note.title}"

    class Meta:
        ordering = ["-uploaded_at"]


class SystemTag(models.Model):
    """
    System tags for linking products and sub-level components to systems in allocations.
    This enables tracking which products/components belong to which systems.
    """

    system = models.ForeignKey("System", on_delete=models.CASCADE, related_name="tags")
    tag_name = models.CharField(max_length=255, help_text="Unique tag identifier for this system")
    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="system_tags")

    # Many-to-many relationships
    products = models.ManyToManyField("Product", blank=True, related_name="system_tags")  # type: ignore[var-annotated]
    sublevels = models.ManyToManyField(  # type: ignore[var-annotated]
        "SubLevel", blank=True, related_name="system_tags"
    )
    sublevel_tools = models.ManyToManyField(  # type: ignore[var-annotated]
        "SubLevelTool", blank=True, related_name="system_tags"
    )
    projects = models.ManyToManyField("Project", blank=True, related_name="system_tags")  # type: ignore[var-annotated]

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.TextField(blank=True, help_text="Optional description of this system configuration")

    class Meta:
        unique_together = ("system", "tag_name")
        ordering = ["system__name", "tag_name"]

    def __str__(self):
        return f"{self.system.name} - {self.tag_name}"

    def get_all_components_count(self):
        """Return total count of all tagged items"""
        return self.products.count() + self.sublevels.count() + self.sublevel_tools.count() + self.projects.count()


class SystemTagHistory(models.Model):
    """
    History tracking for SystemTag modifications.
    Records who made changes, when, and what was changed.
    """

    ACTION_CHOICES = [
        ("created", "Created"),
        ("updated", "Updated"),
        ("deleted", "Deleted"),
        ("item_added", "Item Added"),
        ("item_removed", "Item Removed"),
    ]
    ITEM_TYPE_CHOICES = [
        ("product", "Product"),
        ("sublevel", "Sub Level"),
        ("sublevel_tool", "Sub Level Tool"),
        ("project", "Project"),
        ("tag", "Tag"),
    ]
    system_tag = models.ForeignKey("SystemTag", on_delete=models.CASCADE, related_name="history", null=True, blank=True)
    system_tag_name = models.CharField(max_length=255, help_text="Stored tag name for reference after deletion")
    system_name = models.CharField(max_length=255, help_text="Stored system name for reference")
    stream = models.ForeignKey("Stream", on_delete=models.CASCADE, related_name="tag_history")
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    item_type = models.CharField(max_length=20, choices=ITEM_TYPE_CHOICES, null=True, blank=True)
    item_name = models.CharField(max_length=255, null=True, blank=True, help_text="Name of item added/removed")
    item_id = models.IntegerField(null=True, blank=True, help_text="ID of item added/removed")
    description = models.TextField(blank=True, help_text="Additional details about the change")
    modified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    modified_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-modified_at"]
        verbose_name_plural = "System Tag Histories"

    def __str__(self):
        return f"{self.system_tag_name} - {self.get_action_display()} by {self.modified_by} at {self.modified_at}"
