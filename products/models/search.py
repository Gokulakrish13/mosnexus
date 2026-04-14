# pylint: disable=import-outside-toplevel,missing-class-docstring,no-member
"""Full-Text Search — unified search index for cross-module search.

Uses Django's built-in SearchVector / trigram similarity for typo-tolerant,
instant search across products, documents, vendors, tickets, chat messages,
and notes.  Designed as a lightweight alternative to Elasticsearch that
works with SQLite (basic) and PostgreSQL (full trigram + ranking).
"""

from django.conf import settings
from django.db import models


class SearchIndex(models.Model):
    """Denormalised search index — one row per searchable entity.

    Populated / refreshed by a management command or signal handlers.
    Enables fast cross-module search without hitting every table.
    """

    ENTITY_TYPE_CHOICES = [
        ("product", "Product"),
        ("vendor", "Vendor"),
        ("compliance_doc", "Compliance Document"),
        ("calibration", "Calibration Record"),
        ("system", "System"),
        ("ticket", "System Ticket"),
        ("chat_message", "Chat Message"),
        ("note", "Note"),
        ("project", "Project"),
        ("purchase_order", "Purchase Order"),
        ("build_server", "Build Server"),
        ("waste_record", "Waste Record"),
        ("support_ticket", "Support Ticket"),
        ("approval_request", "Approval Request"),
    ]

    entity_type = models.CharField(max_length=30, choices=ENTITY_TYPE_CHOICES, db_index=True)
    entity_id = models.PositiveIntegerField(db_index=True)
    title = models.CharField(max_length=500)
    subtitle = models.CharField(max_length=500, blank=True)
    body = models.TextField(blank=True, help_text="Concatenated searchable text")
    url = models.CharField(max_length=500, blank=True, help_text="Relative URL to the entity detail page")
    icon = models.CharField(max_length=60, blank=True, help_text="Font Awesome icon class")
    stream_name = models.CharField(max_length=100, blank=True, db_index=True)
    business_unit_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    status = models.CharField(max_length=40, blank=True)
    extra_data = models.JSONField(default=dict, blank=True, help_text="Arbitrary metadata for display")
    indexed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-indexed_at"]
        unique_together = ("entity_type", "entity_id")
        indexes = [
            models.Index(fields=["entity_type", "business_unit_id"]),
            models.Index(fields=["title"]),
        ]

    def __str__(self):
        return f"[{self.entity_type}] {self.title}"


class SearchQueryLog(models.Model):
    """Audit log — tracks what users search for (analytics / autocomplete)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="search_queries",
    )
    query_text = models.CharField(max_length=500)
    results_count = models.PositiveIntegerField(default=0)
    entity_type_filter = models.CharField(max_length=30, blank=True)
    clicked_result_type = models.CharField(max_length=30, blank=True)
    clicked_result_id = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f'"{self.query_text}" by {self.user} ({self.results_count} results)'
