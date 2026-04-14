# pylint: disable=no-member
from products.models._validators import _document_ext_validator

from django.conf import settings
from django.db import models


class AICalibrationReport(models.Model):
    """Stores generated AI calibration reports."""

    calibration_schedule = models.ForeignKey("CalibrationSchedule", on_delete=models.CASCADE, related_name="ai_reports")
    stream = models.ForeignKey("Stream", on_delete=models.SET_NULL, null=True, blank=True)
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    report_data = models.JSONField(default=dict, help_text="Full statistical report data")
    compliance_score = models.FloatField(default=0)
    anomaly_count = models.IntegerField(default=0)
    pass_rate = models.FloatField(default=0)
    recommendations_count = models.IntegerField(default=0)
    report_version = models.CharField(max_length=20, default="1.0")

    class Meta:
        ordering = ["-generated_at"]

    def __str__(self):
        return f"AI Report: {self.calibration_schedule.title} ({self.generated_at:%Y-%m-%d})"


class OCRProcessingResult(models.Model):
    """Stores results from document OCR processing."""

    PROCESSING_STATUS = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    uploaded_file = models.FileField(upload_to="ocr_uploads/%Y/%m/", validators=[_document_ext_validator])
    original_filename = models.CharField(max_length=500)
    file_type = models.CharField(max_length=20, blank=True)
    stream = models.ForeignKey("Stream", on_delete=models.SET_NULL, null=True, blank=True)
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    processed_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=PROCESSING_STATUS, default="pending")

    extracted_text = models.TextField(blank=True)
    ocr_confidence = models.FloatField(default=0)
    document_type = models.CharField(max_length=100, blank=True)
    classification_confidence = models.FloatField(default=0)
    extracted_fields = models.JSONField(default=dict)
    processing_errors = models.TextField(blank=True)

    # Link to existing document (if auto-matched)
    linked_document = models.ForeignKey(
        "ComplianceDocument", on_delete=models.SET_NULL, null=True, blank=True, related_name="ocr_results"
    )

    class Meta:
        ordering = ["-processed_at"]

    def __str__(self):
        return f"OCR: {self.original_filename} ({self.status})"


class NLQueryLog(models.Model):
    """Logs natural language queries and their results."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    query_text = models.TextField()
    detected_intent = models.CharField(max_length=100, blank=True)
    confidence = models.FloatField(default=0)
    classification_method = models.CharField(max_length=20, blank=True)
    parameters = models.JSONField(default=dict)
    result_count = models.IntegerField(default=0)
    was_successful = models.BooleanField(default=True)
    execution_time_ms = models.IntegerField(default=0)
    user_feedback = models.CharField(
        max_length=20,
        blank=True,
        choices=[("helpful", "Helpful"), ("not_helpful", "Not Helpful"), ("wrong", "Wrong Result")],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"NLQ: {self.query_text[:50]} → {self.detected_intent}"


class InventoryForecast(models.Model):
    """Stores generated inventory forecasts."""

    stream = models.ForeignKey("Stream", on_delete=models.SET_NULL, null=True, blank=True)
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    forecast_days = models.IntegerField(default=90)
    forecast_method = models.CharField(max_length=50, blank=True)
    forecast_data = models.JSONField(default=dict, help_text="Full forecast output")
    current_count = models.IntegerField(default=0)
    predicted_end_count = models.FloatField(default=0)
    trend_direction = models.CharField(max_length=20, blank=True)
    trend_change_rate = models.FloatField(default=0)
    threshold_warnings_count = models.IntegerField(default=0)
    summary = models.TextField(blank=True)

    class Meta:
        ordering = ["-generated_at"]

    def __str__(self):
        return f"Forecast: {self.stream or 'All'} ({self.generated_at:%Y-%m-%d})"


class SchedulerRecommendation(models.Model):
    """Stores smart scheduling recommendations."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="scheduler_recs"
    )
    stream = models.ForeignKey("Stream", on_delete=models.SET_NULL, null=True, blank=True)
    system = models.ForeignKey("System", on_delete=models.SET_NULL, null=True, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    desired_date = models.DateField(null=True, blank=True)
    desired_duration_hours = models.IntegerField(default=2)
    recommendations_data = models.JSONField(default=dict)
    selected_slot = models.JSONField(default=dict, blank=True, help_text="The slot the user actually chose")
    was_accepted = models.BooleanField(default=False)

    class Meta:
        ordering = ["-requested_at"]

    def __str__(self):
        return f"Scheduler Rec: {self.user} ({self.requested_at:%Y-%m-%d})"


class AIModelTrainingLog(models.Model):
    """Tracks AI model training runs."""

    MODEL_TYPES = [
        ("doc_classifier", "Document Classifier"),
        ("nl_query", "NL Query Classifier"),
        ("inventory_forecast", "Inventory Forecast"),
    ]

    model_type = models.CharField(max_length=50, choices=MODEL_TYPES)
    trained_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    trained_at = models.DateTimeField(auto_now_add=True)
    training_samples = models.IntegerField(default=0)
    training_result = models.JSONField(default=dict)
    was_successful = models.BooleanField(default=True)
    error_message = models.TextField(blank=True)
    model_file_path = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-trained_at"]

    def __str__(self):
        return f"Training: {self.get_model_type_display()} ({self.trained_at:%Y-%m-%d})"


# ─── AI Usage Analytics & Anomaly Detection ──────────────────────────────────
class UsageAnalyticsReport(models.Model):
    """Stores AI-generated usage pattern analytics reports."""

    stream = models.ForeignKey("Stream", on_delete=models.SET_NULL, null=True, blank=True)
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    analysis_period_days = models.IntegerField(default=90)
    report_data = models.JSONField(default=dict, help_text="Full analytics report JSON")
    peak_hour = models.CharField(max_length=10, blank=True)
    avg_utilization = models.FloatField(default=0)
    underutilized_count = models.IntegerField(default=0)
    overutilized_count = models.IntegerField(default=0)
    total_bookings = models.IntegerField(default=0)
    conflict_rate = models.FloatField(default=0)
    recommendation_count = models.IntegerField(default=0)

    class Meta:
        ordering = ["-generated_at"]

    def __str__(self):
        return f"Usage Analytics: {self.stream} ({self.generated_at:%Y-%m-%d})"


class AnomalyDetectionReport(models.Model):
    """Stores AI-generated anomaly / duplicate detection scan results."""

    SCAN_TYPES = [
        ("full", "Full Scan"),
        ("duplicates", "Duplicates Only"),
        ("anomalies", "Anomalies Only"),
        ("quality", "Data Quality Only"),
    ]

    stream = models.ForeignKey("Stream", on_delete=models.SET_NULL, null=True, blank=True)
    scanned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    scanned_at = models.DateTimeField(auto_now_add=True)
    scan_type = models.CharField(max_length=20, choices=SCAN_TYPES, default="full")
    scan_period_days = models.IntegerField(default=90)
    report_data = models.JSONField(default=dict, help_text="Full scan report JSON")
    risk_score = models.IntegerField(default=100, help_text="Overall health score 0-100")
    risk_grade = models.CharField(max_length=2, blank=True)
    duplicate_groups = models.IntegerField(default=0)
    serial_issues = models.IntegerField(default=0)
    inventory_anomalies_count = models.IntegerField(default=0)
    data_quality_score = models.IntegerField(default=100)

    class Meta:
        ordering = ["-scanned_at"]

    def __str__(self):
        return f"Anomaly Scan: {self.stream} — Grade {self.risk_grade} ({self.scanned_at:%Y-%m-%d})"
