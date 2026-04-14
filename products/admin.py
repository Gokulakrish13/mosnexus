# pylint: disable=missing-class-docstring,too-many-lines
from django.contrib import admin

from .models import (  # Business Unit; Reservation & Booking models; Calibration & Compliance models; Audit Log; Dashboard Widgets; Asset Lifecycle; Inventory Alerts; File Versioning; Maintenance Calendar; AI Features; Site Settings
    AICalibrationReport,
    AIModelTrainingLog,
    AssetLifecycleRecord,
    AssetLifecycleStage,
    AssetLifecycleTransition,
    AuditLog,
    BUDeletionRequest,
    BuildServer,
    BuildServerHistory,
    BuildServerMaintenanceLog,
    BusinessUnit,
    CalibrationCertificate,
    CalibrationRecord,
    CalibrationSchedule,
    Category,
    ComplianceAlert,
    ComplianceDocument,
    ComplianceDocumentVersion,
    DashboardWidget,
    Floor,
    HolisticSystem,
    HolisticSystemHistory,
    HolisticWeeklyData,
    InventoryAlert,
    InventoryForecast,
    InventoryThreshold,
    MaintenanceEvent,
    NLQueryLog,
    Note,
    NoteAttachment,
    OCRProcessingResult,
    OperatingSystem,
    Product,
    ProductHistory,
    Project,
    ProjectAttachment,
    ProjectDependency,
    ProjectMilestone,
    RecurringReservation,
    RecurringReservationInstance,
    RegulatoryChecklist,
    RegulatoryChecklistItem,
    RegulatoryRequirement,
    ReservationConflict,
    ReservationWaitlist,
    SchedulerRecommendation,
    SharedNote,
    SiteSetting,
    SubLevel,
    SubLevelHistory,
    SubLevelTool,
    SubLevelToolHistory,
    SystemTag,
    TLDBadgeRecord,
    UserBUAccess,
    UserDashboardLayout,
    UserDashboardWidget,
)


@admin.register(BusinessUnit)
class BusinessUnitAdmin(admin.ModelAdmin):
    list_display = ("bu_name", "division", "slug", "name", "is_active", "created_at")
    search_fields = ("bu_name", "division", "slug", "name")
    list_filter = ("is_active",)
    ordering = ("bu_name", "division")


@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    list_display = ("__str__", "devtools_protection", "updated_at", "updated_by")
    readonly_fields = ("updated_at", "updated_by")

    def has_add_permission(self, request):
        # Only allow one instance
        return not SiteSetting.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UserBUAccess)
class UserBUAccessAdmin(admin.ModelAdmin):
    list_display = ("custom_user", "business_unit", "granted_by", "granted_at")
    search_fields = ("custom_user__user__username", "business_unit__bu_name", "business_unit__division")
    list_filter = ("business_unit",)
    raw_id_fields = ("custom_user", "granted_by")


@admin.register(BUDeletionRequest)
class BUDeletionRequestAdmin(admin.ModelAdmin):
    list_display = ("business_unit", "status", "requested_by", "requested_at", "reviewed_by", "reviewed_at")
    list_filter = ("status",)
    readonly_fields = ("bu_snapshot", "requested_by", "requested_at", "reviewed_by", "reviewed_at")
    ordering = ("-requested_at",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "serial_number", "category", "created_at")
    search_fields = ("name", "serial_number")
    list_filter = ("category",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "serial_number", "created_at")
    search_fields = ("name", "serial_number")


@admin.register(ProductHistory)
class ProductHistoryAdmin(admin.ModelAdmin):
    list_display = ("product", "action", "user", "timestamp")
    search_fields = ("product__name", "user__username", "action")


@admin.register(SubLevel)
class SubLevelAdmin(admin.ModelAdmin):
    list_display = ("name", "stream", "in_stock", "in_use", "scraped")
    search_fields = ("name", "stream")
    list_filter = ("stream",)


@admin.register(SubLevelHistory)
class SubLevelHistoryAdmin(admin.ModelAdmin):
    list_display = ("sublevel", "action", "by", "at")
    search_fields = ("sublevel__name", "by", "action")


@admin.register(SubLevelTool)
class SubLevelToolAdmin(admin.ModelAdmin):
    list_display = ("name", "stream", "in_stock", "in_use", "scraped")
    search_fields = ("name", "stream")
    list_filter = ("stream",)


@admin.register(SubLevelToolHistory)
class SubLevelToolHistoryAdmin(admin.ModelAdmin):
    list_display = ("subleveltool", "action", "by", "at")
    search_fields = ("subleveltool__name", "by", "action")


@admin.register(SystemTag)
class SystemTagAdmin(admin.ModelAdmin):
    list_display = ("tag_name", "system", "stream", "created_by", "created_at", "get_components_count")
    search_fields = ("tag_name", "system__name", "description")
    list_filter = ("stream", "system", "created_at")
    filter_horizontal = ("products", "sublevels", "sublevel_tools")
    readonly_fields = ("created_at", "created_by")

    def get_components_count(self, obj):
        return obj.get_all_components_count()

    get_components_count.short_description = "Total Components"  # type: ignore[attr-defined]

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "status",
        "priority",
        "start_date",
        "initial_release_date",
        "final_release_date",
        "progress_percentage",
        "expected_progress",
        "stream",
        "created_by",
        "created_at",
    )
    search_fields = ("name", "description", "created_by__username")
    list_filter = (
        "status",
        "priority",
        "stream",
        "created_at",
        "start_date",
        "initial_release_date",
        "final_release_date",
    )
    filter_horizontal = ("team_members",)
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "start_date"

    fieldsets = (
        ("Basic Information", {"fields": ("name", "description", "stream")}),
        ("Timeline", {"fields": ("duration", "start_date", "initial_release_date", "final_release_date")}),
        ("Status & Priority", {"fields": ("status", "priority", "progress_percentage", "expected_progress")}),
        ("Team", {"fields": ("team_members", "created_by")}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


class ProjectMilestoneInline(admin.TabularInline):
    model = ProjectMilestone
    extra = 0


class ProjectAttachmentInline(admin.TabularInline):
    model = ProjectAttachment
    extra = 0
    readonly_fields = ("file_size_display",)


class ProjectDependencyInline(admin.TabularInline):
    model = ProjectDependency
    fk_name = "from_project"
    extra = 0


@admin.register(ProjectMilestone)
class ProjectMilestoneAdmin(admin.ModelAdmin):
    list_display = ("name", "project", "due_date", "is_completed")
    list_filter = ("is_completed", "project")


@admin.register(ProjectAttachment)
class ProjectAttachmentAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "project", "uploaded_by", "created_at")
    list_filter = ("project",)


@admin.register(ProjectDependency)
class ProjectDependencyAdmin(admin.ModelAdmin):
    list_display = ("from_project", "dependency_type", "to_project", "created_at")
    list_filter = ("dependency_type",)


@admin.register(HolisticSystem)
class HolisticSystemAdmin(admin.ModelAdmin):
    list_display = (
        "sr_no",
        "system_availability",
        "allocation_to_sl_no",
        "location_info",
        "system_owner",
        "test_engineer",
        "priority",
        "stream",
        "created_at",
    )
    search_fields = ("sr_no", "system_owner", "test_engineer", "stmi_number", "ecr_number", "location_info")
    list_filter = ("system_availability", "priority", "stream", "created_at")
    readonly_fields = ("created_at", "updated_at", "created_by", "updated_by")

    fieldsets = (
        ("Core Information", {"fields": ("sr_no", "system_availability", "allocation_to_sl_no", "stream")}),
        ("System Details", {"fields": ("location_info", "stmi_number", "system_owner", "ecr_number", "test_engineer")}),
        ("Additional Information", {"fields": ("description", "notes", "priority")}),
        ("Metadata", {"fields": ("created_at", "created_by", "updated_at", "updated_by"), "classes": ("collapse",)}),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(HolisticWeeklyData)
class HolisticWeeklyDataAdmin(admin.ModelAdmin):
    list_display = (
        "holistic_system",
        "get_week_label",
        "year",
        "allocation_status",
        "utilization_percentage",
        "assigned_to",
        "hours_used",
    )
    search_fields = ("holistic_system__sr_no", "allocation_status", "assigned_to")
    list_filter = ("year", "week_number", "holistic_system__stream")
    readonly_fields = ("created_at", "updated_at", "updated_by")

    fieldsets = (
        ("Time Period", {"fields": ("holistic_system", "week_number", "year")}),
        (
            "Weekly Metrics",
            {
                "fields": (
                    "allocation_status",
                    "utilization_percentage",
                    "assigned_to",
                    "hours_used",
                    "availability_hours",
                )
            },
        ),
        ("Details", {"fields": ("task_description", "notes")}),
        ("Metadata", {"fields": ("created_at", "updated_at", "updated_by"), "classes": ("collapse",)}),
    )

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(HolisticSystemHistory)
class HolisticSystemHistoryAdmin(admin.ModelAdmin):
    list_display = ("holistic_system", "action", "user", "timestamp")
    search_fields = ("holistic_system__sr_no", "action", "user__username")
    list_filter = ("action", "timestamp")
    readonly_fields = ("timestamp",)


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ("title", "created_by", "is_public", "created_at", "updated_at")
    search_fields = ("title", "content", "created_by__username")
    list_filter = ("is_public", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Note Information", {"fields": ("title", "content", "is_public")}),
        ("Meta Information", {"fields": ("created_by", "updated_by", "created_at", "updated_at")}),
    )


@admin.register(NoteAttachment)
class NoteAttachmentAdmin(admin.ModelAdmin):
    list_display = ("note", "original_filename", "file_type", "file_size", "uploaded_by", "uploaded_at")
    search_fields = ("note__title", "original_filename", "uploaded_by__username")
    list_filter = ("file_type", "uploaded_at")
    readonly_fields = ("uploaded_at", "file_size", "content_type")


@admin.register(SharedNote)
class SharedNoteAdmin(admin.ModelAdmin):
    list_display = ("note", "shared_by", "shared_with", "shared_at", "is_read")
    search_fields = ("note__title", "shared_by__username", "shared_with__username")
    list_filter = ("shared_at", "is_read")
    readonly_fields = ("shared_at",)

    fieldsets = (
        ("Share Information", {"fields": ("note", "shared_by", "shared_with", "message")}),
        ("Status", {"fields": ("is_read", "shared_at")}),
    )


@admin.register(BuildServer)
class BuildServerAdmin(admin.ModelAdmin):
    """Admin configuration for BuildServer model."""

    list_display = ("hostname", "ip_address", "stream_type", "location", "floor", "owner", "status", "created_at")
    list_filter = ("stream_type", "status", "floor", "stream", "created_at")
    search_fields = ("hostname", "ip_address", "location", "owner", "purpose")
    readonly_fields = ("created_at", "created_by", "updated_at", "updated_by")

    fieldsets = (
        ("Basic Information", {"fields": ("hostname", "ip_address", "stream_type", "stream", "status")}),
        ("Location Details", {"fields": ("location", "floor", "owner")}),
        (
            "Hardware Specifications",
            {"fields": ("operating_system", "cpu_cores", "ram_gb", "storage_gb"), "classes": ("collapse",)},
        ),
        ("Network Details", {"fields": ("mac_address", "domain", "ssh_port"), "classes": ("collapse",)}),
        (
            "Business Information",
            {
                "fields": ("purpose", "project_allocation", "cost_center", "procurement_date", "warranty_expiry"),
                "classes": ("collapse",),
            },
        ),
        (
            "Contact Information",
            {"fields": ("primary_contact", "secondary_contact", "contact_email"), "classes": ("collapse",)},
        ),
        (
            "Maintenance",
            {"fields": ("last_maintenance", "next_maintenance", "uptime_percentage"), "classes": ("collapse",)},
        ),
        ("Additional Information", {"fields": ("notes", "tags"), "classes": ("collapse",)}),
        ("Tracking", {"fields": ("created_at", "created_by", "updated_at", "updated_by"), "classes": ("collapse",)}),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(BuildServerHistory)
class BuildServerHistoryAdmin(admin.ModelAdmin):
    list_display = ("build_server", "action", "user", "timestamp", "get_hostname")
    list_filter = ("action", "timestamp")
    search_fields = ("build_server__hostname", "user__username", "action")
    readonly_fields = ("timestamp",)

    def get_hostname(self, obj):
        return obj.build_server.hostname

    get_hostname.short_description = "Hostname"  # type: ignore[attr-defined]


@admin.register(BuildServerMaintenanceLog)
class BuildServerMaintenanceLogAdmin(admin.ModelAdmin):
    list_display = ("build_server", "maintenance_type", "scheduled_date", "completed", "performed_by", "cost")
    list_filter = ("maintenance_type", "completed", "scheduled_date", "performed_by")
    search_fields = ("build_server__hostname", "description", "performed_by", "vendor")
    date_hierarchy = "scheduled_date"

    fieldsets = (
        (
            "Maintenance Information",
            {"fields": ("build_server", "maintenance_type", "scheduled_date", "actual_date", "completed")},
        ),
        ("Details", {"fields": ("description", "performed_by", "duration_hours", "authorized_by")}),
        (
            "Issues & Follow-up",
            {
                "fields": (
                    "issues_found",
                    "actions_taken",
                    "parts_replaced",
                    "requires_followup",
                    "next_maintenance_due",
                ),
                "classes": ("collapse",),
            },
        ),
        ("Cost Information", {"fields": ("cost", "vendor"), "classes": ("collapse",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(Floor)
class FloorAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "is_active", "created_at")
    search_fields = ("name", "description")
    list_filter = ("is_active", "created_at")
    readonly_fields = ("created_at", "updated_at")


@admin.register(OperatingSystem)
class OperatingSystemAdmin(admin.ModelAdmin):
    list_display = ("name", "version", "stream", "is_active", "created_at")
    search_fields = ("name", "version", "description")
    list_filter = ("stream", "is_active", "created_at")
    readonly_fields = ("created_at", "updated_at")
    ordering = ["stream", "name", "version"]


# ============================================================
# RESERVATION & BOOKING MANAGEMENT ADMIN
# ============================================================


@admin.register(RecurringReservation)
class RecurringReservationAdmin(admin.ModelAdmin):
    list_display = ("title", "system", "created_by", "recurrence_type", "start_date", "end_date", "status", "stream")
    list_filter = ("recurrence_type", "status", "stream", "created_at")
    search_fields = ("title", "system__name", "created_by__username")
    readonly_fields = ("created_at", "updated_at", "occurrences_created")
    date_hierarchy = "start_date"

    fieldsets = (
        ("Basic Information", {"fields": ("title", "description", "system", "stream")}),
        ("Users", {"fields": ("created_by", "reserved_for", "project")}),
        (
            "Schedule",
            {
                "fields": (
                    "recurrence_type",
                    "start_date",
                    "end_date",
                    "start_time",
                    "end_time",
                    "days_of_week",
                    "day_of_month",
                    "max_occurrences",
                )
            },
        ),
        ("Status & Priority", {"fields": ("status", "priority")}),
        ("Conflict Handling", {"fields": ("allow_conflicts", "auto_resolve_conflicts"), "classes": ("collapse",)}),
        (
            "Notifications",
            {"fields": ("notify_on_creation", "notify_on_conflict", "reminder_hours_before"), "classes": ("collapse",)},
        ),
        ("Notes", {"fields": ("notes",), "classes": ("collapse",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at", "occurrences_created"), "classes": ("collapse",)}),
    )


@admin.register(RecurringReservationInstance)
class RecurringReservationInstanceAdmin(admin.ModelAdmin):
    list_display = ("recurring_reservation", "reservation_date", "status", "has_conflict")
    list_filter = ("status", "has_conflict", "reservation_date")
    search_fields = ("recurring_reservation__title", "recurring_reservation__system__name")
    date_hierarchy = "reservation_date"


@admin.register(ReservationWaitlist)
class ReservationWaitlistAdmin(admin.ModelAdmin):
    list_display = ("user", "system", "desired_date", "priority", "status", "queue_position", "stream")
    list_filter = ("status", "priority", "stream", "created_at")
    search_fields = ("user__username", "system__name")
    date_hierarchy = "desired_date"

    fieldsets = (
        ("Request Information", {"fields": ("user", "system", "project", "stream")}),
        ("Desired Time", {"fields": ("desired_date", "desired_start_time", "desired_end_time")}),
        (
            "Priority & Flexibility",
            {"fields": ("priority", "is_flexible_date", "is_flexible_time", "flexibility_days")},
        ),
        ("Status", {"fields": ("status", "queue_position")}),
        ("Notes", {"fields": ("reason",), "classes": ("collapse",)}),
    )


@admin.register(ReservationConflict)
class ReservationConflictAdmin(admin.ModelAdmin):
    list_display = ("id", "system", "conflict_type", "conflict_date", "resolution_status", "detected_at")
    list_filter = ("conflict_type", "resolution_status", "detected_at", "stream")
    search_fields = ("system__name",)
    readonly_fields = ("detected_at",)
    date_hierarchy = "conflict_date"


# ============================================================
# CALIBRATION & COMPLIANCE TRACKING ADMIN
# ============================================================


@admin.register(CalibrationSchedule)
class CalibrationScheduleAdmin(admin.ModelAdmin):
    list_display = ("title", "calibration_type", "calibration_interval", "next_calibration_date", "status", "stream")
    list_filter = ("calibration_type", "status", "stream", "next_calibration_date")
    search_fields = ("title", "system__name", "product__name")
    date_hierarchy = "next_calibration_date"

    fieldsets = (
        ("Equipment", {"fields": ("title", "description", "product", "system", "build_server", "stream")}),
        (
            "Schedule",
            {
                "fields": (
                    "calibration_type",
                    "calibration_interval",
                    "interval_unit",
                    "last_calibration_date",
                    "next_calibration_date",
                )
            },
        ),
        ("Procedures", {"fields": ("parameters", "procedures", "equipment_required"), "classes": ("collapse",)}),
        ("Compliance", {"fields": ("regulatory_requirement",)}),
        (
            "Service Provider",
            {"fields": ("service_provider", "service_provider_contact", "estimated_cost"), "classes": ("collapse",)},
        ),
        (
            "Notifications",
            {
                "fields": (
                    "reminder_days_before",
                    "notify_responsible",
                    "notify_lab_incharge",
                    "escalate_if_overdue",
                    "escalation_days",
                ),
                "classes": ("collapse",),
            },
        ),
        ("Responsibility", {"fields": ("responsible_person", "backup_person")}),
        ("Status", {"fields": ("status", "priority")}),
    )


@admin.register(CalibrationRecord)
class CalibrationRecordAdmin(admin.ModelAdmin):
    list_display = ("calibration_schedule", "calibration_date", "result", "performed_by", "approved_by")
    list_filter = ("result", "calibration_date")
    search_fields = ("calibration_schedule__title", "performed_by", "performed_by_user__username")
    date_hierarchy = "calibration_date"


@admin.register(CalibrationCertificate)
class CalibrationCertificateAdmin(admin.ModelAdmin):
    list_display = ("certificate_number", "calibration_record", "issue_date", "expiry_date", "issued_by")
    list_filter = ("expiry_date", "issue_date")
    search_fields = ("certificate_number", "issued_by", "issuing_organization")
    date_hierarchy = "expiry_date"


@admin.register(RegulatoryRequirement)
class RegulatoryRequirementAdmin(admin.ModelAdmin):
    list_display = ("requirement_id", "title", "regulatory_body", "priority", "compliance_status", "effective_date")
    list_filter = ("compliance_status", "priority", "effective_date")
    search_fields = ("requirement_id", "title", "regulatory_body", "description")
    date_hierarchy = "effective_date"

    fieldsets = (
        (
            "Requirement Details",
            {
                "fields": (
                    "requirement_id",
                    "title",
                    "regulatory_body",
                    "regulation_name",
                    "regulation_section",
                    "description",
                )
            },
        ),
        (
            "Applicability",
            {"fields": ("applies_to_products", "applies_to_systems", "applies_to_processes", "applicable_streams")},
        ),
        ("Compliance", {"fields": ("compliance_status", "compliance_evidence", "compliance_gap", "priority")}),
        ("Dates", {"fields": ("effective_date", "compliance_deadline", "last_audit_date", "next_audit_date")}),
        ("Controls", {"fields": ("control_measures", "verification_method", "external_url"), "classes": ("collapse",)}),
        ("Responsibility", {"fields": ("responsible_person", "interpretation"), "classes": ("collapse",)}),
    )


@admin.register(RegulatoryChecklist)
class RegulatoryChecklistAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "regulatory_requirement",
        "assigned_to",
        "target_date",
        "status",
        "completion_percentage",
        "stream",
    )
    list_filter = ("status", "stream", "target_date")
    search_fields = ("title", "regulatory_requirement__title", "assigned_to__username")
    date_hierarchy = "target_date"


class RegulatoryChecklistItemInline(admin.TabularInline):
    model = RegulatoryChecklistItem
    extra = 1
    fields = ("item_number", "description", "priority", "is_completed", "evidence_required")


@admin.register(RegulatoryChecklistItem)
class RegulatoryChecklistItemAdmin(admin.ModelAdmin):
    list_display = ("description", "checklist", "priority", "is_completed", "completed_by", "completed_date")
    list_filter = ("is_completed", "priority", "is_not_applicable")
    search_fields = ("description", "checklist__title")


@admin.register(ComplianceDocument)
class ComplianceDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "document_type", "document_id", "version", "status", "revision_date", "expiry_date")
    list_filter = ("document_type", "status", "stream", "revision_date")
    search_fields = ("title", "document_id", "keywords", "author__username")
    date_hierarchy = "revision_date"

    fieldsets = (
        ("Document Information", {"fields": ("title", "document_id", "document_type", "file", "stream")}),
        ("Version & Status", {"fields": ("version", "status", "revision_date", "previous_version")}),
        ("Metadata", {"fields": ("description", "scope", "keywords")}),
        ("Validity", {"fields": ("effective_date", "expiry_date", "review_date")}),
        ("Authorship", {"fields": ("author", "reviewed_by", "approved_by", "approval_date"), "classes": ("collapse",)}),
        ("Compliance", {"fields": ("regulatory_requirement",), "classes": ("collapse",)}),
    )


@admin.register(ComplianceAlert)
class ComplianceAlertAdmin(admin.ModelAdmin):
    list_display = ("title", "alert_type", "severity", "status", "target_user", "created_at")
    list_filter = ("severity", "alert_type", "status", "stream", "created_at")
    search_fields = ("title", "message", "target_user__username")
    date_hierarchy = "created_at"

    fieldsets = (
        ("Alert Information", {"fields": ("title", "message", "alert_type", "severity", "status", "stream")}),
        (
            "Related Items",
            {"fields": ("related_calibration", "related_certificate", "related_document", "related_requirement")},
        ),
        (
            "Target & Response",
            {
                "fields": (
                    "target_user",
                    "acknowledged_by",
                    "acknowledged_at",
                    "resolved_by",
                    "resolved_at",
                    "resolution_notes",
                )
            },
        ),
        ("Notifications", {"fields": ("email_sent", "email_sent_at", "auto_dismiss_date"), "classes": ("collapse",)}),
    )


# =============================================================================
# FEATURE 1: AUDIT LOG ADMIN
# =============================================================================


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Admin configuration for AuditLog model."""

    list_display = ("timestamp", "severity", "action", "module", "user_display_name", "title", "object_repr")
    list_filter = ("severity", "action", "module", "stream", "timestamp")
    search_fields = ("title", "description", "user_display_name", "object_repr", "ip_address")
    date_hierarchy = "timestamp"
    readonly_fields = (
        "timestamp",
        "user",
        "user_display_name",
        "content_type",
        "object_id",
        "object_repr",
        "ip_address",
        "user_agent",
        "request_method",
        "request_path",
        "old_values",
        "new_values",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False  # Prevent deletion of audit logs to preserve non-repudiation


# =============================================================================
# FEATURE 2: DASHBOARD WIDGETS ADMIN
# =============================================================================


@admin.register(DashboardWidget)
class DashboardWidgetAdmin(admin.ModelAdmin):
    list_display = ("name", "widget_type", "default_size", "is_active", "requires_stream", "min_role")
    list_filter = ("is_active", "widget_type", "default_size")
    search_fields = ("name", "description")


@admin.register(UserDashboardLayout)
class UserDashboardLayoutAdmin(admin.ModelAdmin):
    list_display = ("user", "stream", "is_customized", "theme", "updated_at")
    list_filter = ("is_customized", "theme")
    search_fields = ("user__username",)


@admin.register(UserDashboardWidget)
class UserDashboardWidgetAdmin(admin.ModelAdmin):
    list_display = ("layout", "widget", "position_row", "position_col", "size", "is_visible")
    list_filter = ("size", "is_visible", "is_collapsed")


# =============================================================================
# FEATURE 3: ASSET LIFECYCLE ADMIN
# =============================================================================


@admin.register(AssetLifecycleStage)
class AssetLifecycleStageAdmin(admin.ModelAdmin):
    list_display = ("name", "stage_type", "order", "requires_approval", "is_active", "color")
    list_filter = ("is_active", "requires_approval")
    search_fields = ("name", "description")
    filter_horizontal = ("allowed_from_stages",)
    ordering = ("order",)


class AssetLifecycleTransitionInline(admin.TabularInline):
    model = AssetLifecycleTransition
    extra = 0
    readonly_fields = ("from_stage", "to_stage", "transitioned_by", "approved_by", "timestamp")


@admin.register(AssetLifecycleRecord)
class AssetLifecycleRecordAdmin(admin.ModelAdmin):
    """Admin configuration for AssetLifecycleRecord model."""

    list_display = ("product", "current_stage", "condition", "purchase_date", "purchase_cost", "warranty_status")
    list_filter = ("current_stage", "condition", "depreciation_method")
    search_fields = ("product__name", "product__serial_number", "vendor", "purchase_order_number")
    inlines = [AssetLifecycleTransitionInline]

    fieldsets = (
        ("Asset", {"fields": ("product", "current_stage", "condition")}),
        (
            "Procurement",
            {"fields": ("purchase_date", "purchase_cost", "vendor", "purchase_order_number", "invoice_number")},
        ),
        ("Warranty", {"fields": ("warranty_start_date", "warranty_end_date", "warranty_provider", "warranty_terms")}),
        (
            "Depreciation",
            {"fields": ("expected_lifespan_years", "salvage_value", "depreciation_method"), "classes": ("collapse",)},
        ),
        (
            "Disposal",
            {
                "fields": (
                    "disposal_date",
                    "disposal_method",
                    "disposal_value",
                    "disposal_notes",
                    "disposal_authorized_by",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def warranty_status(self, obj):
        return obj.warranty_status

    warranty_status.short_description = "Warranty"  # type: ignore[attr-defined]


@admin.register(AssetLifecycleTransition)
class AssetLifecycleTransitionAdmin(admin.ModelAdmin):
    list_display = ("lifecycle", "from_stage", "to_stage", "transitioned_by", "timestamp")
    list_filter = ("from_stage", "to_stage", "timestamp")
    search_fields = ("lifecycle__product__name", "note")
    date_hierarchy = "timestamp"
    readonly_fields = ("timestamp",)


# =============================================================================
# FEATURE 4: INVENTORY ALERTS ADMIN
# =============================================================================


@admin.register(InventoryThreshold)
class InventoryThresholdAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "applies_to",
        "minimum_quantity",
        "critical_quantity",
        "reorder_point",
        "is_active",
        "stream",
    )
    list_filter = ("applies_to", "is_active", "stream")
    search_fields = ("name",)


@admin.register(InventoryAlert)
class InventoryAlertAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "alert_type",
        "severity",
        "status",
        "item_name",
        "current_quantity",
        "threshold_value",
        "created_at",
    )
    list_filter = ("severity", "status", "alert_type", "stream")
    search_fields = ("title", "item_name", "message")
    date_hierarchy = "created_at"


# =============================================================================
# FEATURE 5: COMPLIANCE DOCUMENT VERSIONING ADMIN
# =============================================================================


@admin.register(ComplianceDocumentVersion)
class ComplianceDocumentVersionAdmin(admin.ModelAdmin):
    list_display = (
        "document",
        "version_number",
        "version_label",
        "is_current",
        "change_type",
        "created_by",
        "created_at",
    )
    list_filter = ("is_current", "change_type", "created_at")
    search_fields = ("document__title", "version_number", "change_summary")
    date_hierarchy = "created_at"


# =============================================================================
# FEATURE 6: MAINTENANCE CALENDAR ADMIN
# =============================================================================


@admin.register(MaintenanceEvent)
class MaintenanceEventAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "event_type",
        "status",
        "priority",
        "start_datetime",
        "end_datetime",
        "assigned_to",
        "stream",
    )
    list_filter = ("event_type", "status", "priority", "stream", "recurrence")
    search_fields = ("title", "description", "assigned_to__username")
    date_hierarchy = "start_datetime"

    fieldsets = (
        ("Event Details", {"fields": ("title", "description", "event_type", "status", "priority", "color")}),
        ("Scheduling", {"fields": ("start_datetime", "end_datetime", "all_day", "recurrence", "recurrence_end_date")}),
        ("Linked Objects", {"fields": ("build_server", "system", "calibration_schedule", "product", "stream")}),
        ("People", {"fields": ("assigned_to", "created_by")}),
        (
            "Completion",
            {
                "fields": ("completed_at", "completed_by", "completion_notes", "actual_duration_hours"),
                "classes": ("collapse",),
            },
        ),
        ("Cost", {"fields": ("estimated_cost", "actual_cost"), "classes": ("collapse",)}),
    )


# =============================================================================
# AI FEATURE ADMIN REGISTRATIONS
# =============================================================================


@admin.register(AICalibrationReport)
class AICalibrationReportAdmin(admin.ModelAdmin):
    list_display = (
        "calibration_schedule",
        "stream",
        "compliance_score",
        "pass_rate",
        "anomaly_count",
        "generated_at",
        "generated_by",
    )
    list_filter = ("stream", "generated_at")
    search_fields = ("calibration_schedule__title",)
    readonly_fields = ("report_data",)


@admin.register(OCRProcessingResult)
class OCRProcessingResultAdmin(admin.ModelAdmin):
    list_display = (
        "original_filename",
        "document_type",
        "classification_confidence",
        "status",
        "processed_at",
        "processed_by",
    )
    list_filter = ("status", "document_type", "stream")
    search_fields = ("original_filename", "extracted_text")
    readonly_fields = ("extracted_text", "extracted_fields")


@admin.register(NLQueryLog)
class NLQueryLogAdmin(admin.ModelAdmin):
    list_display = (
        "query_text",
        "detected_intent",
        "confidence",
        "was_successful",
        "execution_time_ms",
        "created_at",
        "user",
    )
    list_filter = ("was_successful", "detected_intent", "classification_method")
    search_fields = ("query_text",)
    readonly_fields = ("parameters",)


@admin.register(InventoryForecast)
class InventoryForecastAdmin(admin.ModelAdmin):
    list_display = (
        "stream",
        "forecast_days",
        "forecast_method",
        "current_count",
        "predicted_end_count",
        "trend_direction",
        "generated_at",
    )
    list_filter = ("stream", "forecast_method", "trend_direction")
    readonly_fields = ("forecast_data",)


@admin.register(SchedulerRecommendation)
class SchedulerRecommendationAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "stream",
        "system",
        "desired_date",
        "desired_duration_hours",
        "was_accepted",
        "requested_at",
    )
    list_filter = ("stream", "was_accepted")
    readonly_fields = ("recommendations_data", "selected_slot")


@admin.register(AIModelTrainingLog)
class AIModelTrainingLogAdmin(admin.ModelAdmin):
    list_display = ("model_type", "trained_by", "training_samples", "was_successful", "trained_at")
    list_filter = ("model_type", "was_successful")
    readonly_fields = ("training_result",)


@admin.register(TLDBadgeRecord)
class TLDBadgeRecordAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "email",
        "tld_number",
        "code1_id",
        "employee_id",
        "year",
        "quarter",
        "renewal_status",
        "business_unit",
    )
    list_filter = ("business_unit", "year", "quarter", "renewal_status")
    search_fields = ("name", "email", "tld_number", "code1_id", "employee_id")
    ordering = ("-year", "quarter", "name")


# =========================================================================
# APPROVAL WORKFLOWS
# =========================================================================
from .models import (
    ApprovalAutoTrigger,
    ApprovalComment,
    ApprovalRequest,
    ApprovalStepAction,
    ApprovalStepTemplate,
    ApprovalWorkflowTemplate,
    SearchIndex,
    SearchQueryLog,
)


@admin.register(ApprovalWorkflowTemplate)
class ApprovalWorkflowTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "entity_type", "business_unit", "is_active", "created_at")
    list_filter = ("entity_type", "is_active", "business_unit")
    search_fields = ("name", "description")
    ordering = ("name",)


@admin.register(ApprovalStepTemplate)
class ApprovalStepTemplateAdmin(admin.ModelAdmin):
    list_display = ("template", "order", "name", "approver_type", "approver_role", "is_mandatory")
    list_filter = ("approver_type",)
    ordering = ("template", "order")


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "priority", "template", "requested_by", "current_step", "total_steps", "created_at")
    list_filter = ("status", "priority", "business_unit")
    search_fields = ("title", "description")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at", "completed_at")


@admin.register(ApprovalStepAction)
class ApprovalStepActionAdmin(admin.ModelAdmin):
    list_display = ("request", "step_order", "step_name", "action", "acted_by", "acted_at")
    list_filter = ("action",)
    ordering = ("request", "step_order")


@admin.register(ApprovalComment)
class ApprovalCommentAdmin(admin.ModelAdmin):
    list_display = ("request", "author", "created_at")
    ordering = ("-created_at",)


@admin.register(ApprovalAutoTrigger)
class ApprovalAutoTriggerAdmin(admin.ModelAdmin):
    list_display = ("name", "event_action", "template", "priority", "is_active", "business_unit", "created_at")
    list_filter = ("event_action", "is_active", "priority", "business_unit")
    search_fields = ("name",)
    ordering = ("-created_at",)


# =========================================================================
# FULL-TEXT SEARCH
# =========================================================================


@admin.register(SearchIndex)
class SearchIndexAdmin(admin.ModelAdmin):
    list_display = ("entity_type", "title", "stream_name", "status", "indexed_at")
    list_filter = ("entity_type",)
    search_fields = ("title", "body")
    ordering = ("-indexed_at",)


@admin.register(SearchQueryLog)
class SearchQueryLogAdmin(admin.ModelAdmin):
    list_display = ("query_text", "user", "results_count", "entity_type_filter", "created_at")
    list_filter = ("entity_type_filter",)
    search_fields = ("query_text",)
    ordering = ("-created_at",)


# =========================================================================
# SHIFT HANDOVER LOG
# =========================================================================
from .models import (
    ShiftHandoverAuditLog,
    ShiftHandoverComment,
    ShiftHandoverLog,
    ShiftType,
)


@admin.register(ShiftType)
class ShiftTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "start_time", "end_time", "business_unit", "is_active", "sort_order")
    list_filter = ("business_unit", "is_active")
    search_fields = ("name", "code")
    ordering = ("business_unit", "sort_order")


class ShiftHandoverCommentInline(admin.TabularInline):
    model = ShiftHandoverComment
    extra = 0
    readonly_fields = ("author", "created_at")


@admin.register(ShiftHandoverLog)
class ShiftHandoverLogAdmin(admin.ModelAdmin):
    list_display = ("handover_number", "stream", "shift_type", "shift_date", "status", "priority", "outgoing_lead", "acknowledged_by", "created_at")
    list_filter = ("status", "priority", "business_unit", "stream")
    search_fields = ("handover_number", "systems_running", "pending_actions", "blockers_issues", "safety_notes")
    ordering = ("-shift_date", "-created_at")
    readonly_fields = ("handover_number", "created_at", "updated_at", "acknowledged_at")
    inlines = [ShiftHandoverCommentInline]


@admin.register(ShiftHandoverComment)
class ShiftHandoverCommentAdmin(admin.ModelAdmin):
    list_display = ("handover", "author", "created_at")
    ordering = ("-created_at",)


@admin.register(ShiftHandoverAuditLog)
class ShiftHandoverAuditLogAdmin(admin.ModelAdmin):
    list_display = ("handover", "action", "performed_by", "performed_at")
    list_filter = ("action",)
    ordering = ("-performed_at",)
