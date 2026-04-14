# pylint: disable=missing-class-docstring,no-else-return,no-member
from products.models._validators import _document_ext_validator

from django.conf import settings
from django.db import models


class ZenitionProduct(models.Model):
    name = models.CharField(max_length=255)
    business_unit = models.ForeignKey(
        "BusinessUnit",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="zenition_products",
        help_text="Business Unit this product belongs to",
    )

    class Meta:
        unique_together = ("name", "business_unit")

    def __str__(self):
        return self.name


class ProductEntry(models.Model):
    PRODUCT_TYPE_CHOICES = [
        ("OS", "OS"),
        ("Binaries", "Binaries"),
    ]
    zenition_product = models.ForeignKey("ZenitionProduct", related_name="entries", on_delete=models.CASCADE)
    entry_type = models.CharField(max_length=20, choices=PRODUCT_TYPE_CHOICES)
    category = models.CharField(max_length=255)  # Equipment type: MVS, Stand PC, or Apps PC
    subcategory = models.CharField(max_length=255, blank=True, null=True)
    link = models.URLField(max_length=500)
    os_system_type = models.ForeignKey(
        "OSSystemType", on_delete=models.SET_NULL, null=True, blank=True, verbose_name="OS System Type"
    )
    binaries_system_type = models.ForeignKey(
        "BinariesSystemType", on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Binaries System Type"
    )

    def __str__(self):
        return f"{self.zenition_product.name} - {self.entry_type} - {self.category} - {self.subcategory}"


class OSSystemType(models.Model):
    name = models.CharField(max_length=255, unique=True, verbose_name="OS System Type")
    description = models.TextField(blank=True, null=True, verbose_name="Description")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="created_os_system_types",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="updated_os_system_types",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "OS System Type"
        verbose_name_plural = "OS System Types"
        ordering = ["name"]

    def __str__(self):
        return self.name


class BinariesSystemType(models.Model):
    name = models.CharField(max_length=255, unique=True, verbose_name="Binaries System Type")
    description = models.TextField(blank=True, null=True, verbose_name="Description")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="created_binaries_system_types",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="updated_binaries_system_types",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Binaries System Type"
        verbose_name_plural = "Binaries System Types"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Communication(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    message = models.TextField()
    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    page = models.CharField(max_length=64, default="build_os_info")

    def __str__(self):
        return f"{self.user.username}: {self.message[:30]}{'...' if len(self.message) > 30 else ''}"


class CommunicationAttachment(models.Model):
    communication = models.ForeignKey(
        "Communication", related_name="attachments", on_delete=models.CASCADE, null=True, blank=True
    )
    file = models.FileField(upload_to="communication_attachments/%Y/%m/", validators=[_document_ext_validator])
    original_filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField()
    content_type = models.CharField(max_length=100)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return f"{self.original_filename} - {self.uploaded_by.username if self.uploaded_by else 'Unknown'}"

    @property
    def is_image(self):
        return self.content_type.startswith("image/")

    @property
    def file_size_formatted(self):
        """Return formatted file size"""
        size = self.file_size
        if size < 1024:
            return f"{size} Bytes"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.1f} GB"
