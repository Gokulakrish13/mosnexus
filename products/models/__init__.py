"""Products models package - split for maintainability."""

from products.models._validators import (  # noqa: F401
    _document_ext_validator,
    _excel_ext_validator,
    _image_ext_validator,
)
from products.models.ai_reports import (  # noqa: F401
    AICalibrationReport,
    AIModelTrainingLog,
    AnomalyDetectionReport,
    InventoryForecast,
    NLQueryLog,
    OCRProcessingResult,
    SchedulerRecommendation,
    UsageAnalyticsReport,
)
from products.models.assets import (  # noqa: F401
    AssetLifecycleRecord,
    AssetLifecycleStage,
    AssetLifecycleTransition,
    InventoryAlert,
    InventoryThreshold,
)
from products.models.audit_dashboard import (  # noqa: F401
    AuditLog,
    DashboardWidget,
    UserDashboardLayout,
    UserDashboardWidget,
)
from products.models.calibration import (  # noqa: F401
    CalibrationCertificate,
    CalibrationRecord,
    CalibrationSchedule,
)
from products.models.compliance import (  # noqa: F401
    ComplianceAlert,
    ComplianceDocument,
    RegulatoryChecklist,
    RegulatoryChecklistItem,
    RegulatoryRequirement,
)
from products.models.core import (  # noqa: F401
    Category,
    Location,
    Participant,
    Product,
    ProductHistory,
    ProductImage,
    SystemAllocation,
    SystemTicket,
    SystemTicketComment,
)
from products.models.features_tracking import (  # noqa: F401
    Feature,
    FeatureRoleAccess,
    LegacyExcelUpload,
    PersonalTask,
    SubLevel,
    SubLevelHistory,
    SubLevelTool,
    SubLevelToolHistory,
    SystemStatus,
    TestEnvironment,
    UsageTracking,
    UserSession,
    zenition_upload_path,
)
from products.models.holistic_infra import (  # noqa: F401
    BuildServer,
    BuildServerHistory,
    BuildServerMaintenanceLog,
    Floor,
    HolisticSystem,
    HolisticSystemHistory,
    HolisticWeeklyData,
    OperatingSystem,
    SharedNote,
)
from products.models.maintenance import (  # noqa: F401
    ComplianceDocumentVersion,
    MaintenanceEvent,
)
from products.models.notes_tags import (  # noqa: F401
    Note,
    NoteAttachment,
    NoteTag,
    SystemTag,
    SystemTagHistory,
)
from products.models.onboarding_support import (  # noqa: F401
    LiveSupportMessage,
    LiveSupportSession,
    OnboardingProgress,
    SupportTicket,
    SupportTicketReply,
    TLDBadgeAuditLog,
    TLDBadgeRecord,
)
from products.models.product_types import (  # noqa: F401
    BinariesSystemType,
    Communication,
    CommunicationAttachment,
    OSSystemType,
    ProductEntry,
    ZenitionProduct,
)
from products.models.projects_resources import (  # noqa: F401
    Project,
    ProjectAttachment,
    ProjectDependency,
    ProjectMilestone,
    ResourceAllocation,
    ResourceAllocationLock,
    ResourceAllocationYear,
    ResourceCellNote,
    ResourceComponentType,
    ResourceLocation,
    ResourceManager,
    ResourcePerson,
    ResourceRole,
    ResourceWeeklyAllocation,
)
from products.models.reservations import (  # noqa: F401
    RecurringReservation,
    RecurringReservationInstance,
    ReservationConflict,
    ReservationWaitlist,
)
from products.models.site_settings import (  # noqa: F401
    BUDeletionRequest,
    BUShowcaseProduct,
    DemoRequest,
    SiteSetting,
    VulnerabilityReport,
    bu_showcase_image_path,
)
from products.models.system import (  # noqa: F401
    BusinessUnit,
    Stream,
    StreamDeletionHistory,
    System,
    SystemDowntime,
    SystemDowntimeMetrics,
    SystemMetrics,
    SystemStatusHistory,
    UserDataVersion,
)
from products.models.users import (  # noqa: F401
    CustomUser,
    Notification,
    UserBUAccess,
    UserRole,
    UserStreamAccess,
)
from products.models.vendors_chat import (  # noqa: F401
    ChatAttachment,
    ChatMessage,
    ChatReaction,
    ChatReadReceipt,
    ChatRoom,
    ChatRoomMember,
    Vendor,
    VendorContract,
    VendorDeliveryReceipt,
    VendorDeliveryReceiptItem,
    VendorPerformanceLog,
    VendorPurchaseOrder,
    VendorPurchaseOrderItem,
)
from products.models.waste import (  # noqa: F401
    WasteAuditLog,
    WasteCategory,
    WasteDisposalSchedule,
    WasteRecord,
)
from products.models.approval_workflows import (  # noqa: F401
    DISCOVERABLE_ENTITY_TYPES,
    DISCOVERABLE_EVENT_TYPES,
    ApprovalAutoTrigger,
    ApprovalComment,
    ApprovalEntityType,
    ApprovalEventType,
    ApprovalRequest,
    ApprovalStepAction,
    ApprovalStepTemplate,
    ApprovalWorkflowTemplate,
    ensure_system_types,
)
from products.models.search import (  # noqa: F401
    SearchIndex,
    SearchQueryLog,
)
from products.models.shift_handover import (  # noqa: F401
    ShiftHandoverAuditLog,
    ShiftHandoverComment,
    ShiftHandoverLog,
    ShiftType,
)
