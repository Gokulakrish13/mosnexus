import base64  # noqa: F401
import json
import logging
import os
import re  # noqa: F401
from datetime import date, datetime, timedelta
from datetime import timezone as _dt_timezone  # noqa: F401 — stdlib timezone class
from io import BytesIO  # noqa: F401

import openpyxl  # noqa: F401
import pandas as pd  # noqa: F401
import qrcode  # noqa: F401
from openpyxl.utils import get_column_letter  # noqa: F401
from PIL import Image as PILImage  # noqa: F401
from PIL import ImageDraw, ImageFont  # noqa: F401
from reportlab.lib import colors  # noqa: F401
from reportlab.lib.pagesizes import landscape, letter  # noqa: F401
from reportlab.pdfgen import canvas  # noqa: F401
from reportlab.platypus import Table, TableStyle

from django.contrib import messages  # noqa: F401
from django.contrib.auth import authenticate, get_user_model, login, logout  # noqa: F401
from django.contrib.auth.decorators import login_not_required, login_required
from django.contrib.auth.models import User  # noqa: F401
from django.core.files.storage import default_storage  # noqa: F401
from django.db import models  # noqa: F401
from django.db.models import Q
from django.http import FileResponse, HttpResponse, JsonResponse  # noqa: F401
from django.shortcuts import get_object_or_404, redirect, render  # noqa: F401
from django.template.loader import render_to_string  # noqa: F401
from django.utils import timezone  # noqa: F401
from django.utils.html import escape  # noqa: F401
from django.views.decorators.http import require_GET, require_http_methods, require_POST  # noqa: F401

from ..models import (  # noqa: F401
    AICalibrationReport,
    AIModelTrainingLog,
    AnomalyDetectionReport,
    AssetLifecycleRecord,
    AssetLifecycleStage,
    AssetLifecycleTransition,
    AuditLog,
    BUDeletionRequest,
    BuildServer,
    BuildServerHistory,
    BuildServerMaintenanceLog,
    CalibrationCertificate,
    CalibrationRecord,
    CalibrationSchedule,
    Category,
    ComplianceAlert,
    ComplianceDocument,
    ComplianceDocumentVersion,
    CustomUser,
    DashboardWidget,
    Floor,
    HolisticSystem,
    HolisticSystemHistory,
    HolisticWeeklyData,
    InventoryAlert,
    InventoryForecast,
    InventoryThreshold,
    LegacyExcelUpload,
    Location,
    MaintenanceEvent,
    NLQueryLog,
    Note,
    NoteAttachment,
    NoteTag,
    OCRProcessingResult,
    OperatingSystem,
    Participant,
    Product,
    ProductHistory,
    Project,
    RecurringReservation,
    RecurringReservationInstance,
    RegulatoryChecklist,
    RegulatoryRequirement,
    ReservationConflict,
    ReservationWaitlist,
    SchedulerRecommendation,
    SharedNote,
    Stream,
    SubLevel,
    SubLevelHistory,
    SubLevelTool,
    SubLevelToolHistory,
    System,
    SystemDowntime,
    SystemDowntimeMetrics,
    SystemMetrics,
    SystemStatus,
    SystemStatusHistory,
    SystemTag,
    SystemTagHistory,
    TLDBadgeAuditLog,
    TLDBadgeRecord,
    UsageAnalyticsReport,
    UsageTracking,
    UserBUAccess,
    UserDashboardLayout,
    UserDashboardWidget,
    UserDataVersion,
    UserRole,
    UserSession,
    UserStreamAccess,
)
from ..models import Vendor as VendorModel  # noqa: F401
from ..models import (  # noqa: F401
    WasteAuditLog,
    WasteCategory,
    WasteDisposalSchedule,
    WasteRecord,
    ZenitionProduct,
)
from ..models import (  # noqa: F401
    ShiftHandoverAuditLog,
    ShiftHandoverComment,
    ShiftHandoverLog,
    ShiftType,
)
from ..utils import get_stream_or_404  # noqa: F401

logger = logging.getLogger(__name__)
import csv  # noqa: F401, E402
import io  # noqa: F401, E402
import json  # noqa: E402, F811
import logging  # noqa: E402
import sys  # noqa: F401, E402
from datetime import date, datetime, timedelta  # noqa: F401, E402, F811

import numpy as np  # noqa: F401, E402
from openpyxl import Workbook  # noqa: F401, E402
from reportlab.lib.pagesizes import A3, landscape  # noqa: F401, E402, F811
from reportlab.lib.styles import getSampleStyleSheet  # noqa: F401, E402
from reportlab.lib.units import mm  # noqa: F401, E402
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: F401, E402, F811

from django.conf import settings  # noqa: F401, E402
from django.contrib.auth import update_session_auth_hash  # noqa: F401, E402
from django.contrib.auth.decorators import user_passes_test  # noqa: F401, E402
from django.contrib.auth.hashers import check_password  # noqa: F401, E402
from django.contrib.auth.mixins import LoginRequiredMixin  # noqa: F401, E402
from django.contrib.auth.views import PasswordChangeDoneView, PasswordChangeView  # noqa: E402
from django.contrib.contenttypes.models import ContentType  # noqa: F401, E402
from django.core.files.base import ContentFile  # noqa: F401, E402
from django.core.paginator import Paginator  # noqa: F401, E402
from django.db import IntegrityError, transaction  # noqa: F401, E402
from django.db.models import Avg, Count, F, Q, Sum  # noqa: F401, E402, F811
from django.db.models.functions import TruncMonth  # noqa: F401, E402
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse  # noqa: F401, E402, F811
from django.urls import reverse, reverse_lazy  # noqa: F401, E402
from django.utils.timezone import localtime, make_aware  # noqa: F401, E402

# Additional imports needed by submodules (were scattered in original monolithic file)
from django.views.decorators.cache import never_cache  # noqa: F401, E402
from django.views.decorators.http import require_POST  # noqa: F401, E402, F811
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView  # noqa: F401, E402

from ..models import (  # noqa: F401, E402, F811
    BinariesSystemType,
    BUShowcaseProduct,
    BusinessUnit,
    ChatAttachment,
    ChatMessage,
    ChatReaction,
    ChatReadReceipt,
    ChatRoom,
    ChatRoomMember,
    Communication,
    CommunicationAttachment,
    CustomUser,
    Feature,
    FeatureRoleAccess,
    LegacyExcelUpload,
    LiveSupportMessage,
    LiveSupportSession,
    Notification,
    OnboardingProgress,
    OSSystemType,
    PersonalTask,
    ProductEntry,
    ProductImage,
    RegulatoryChecklistItem,
    StreamDeletionHistory,
    SupportTicket,
    System,
    SystemAllocation,
    TestEnvironment,
    Vendor,
    VendorContract,
    VendorDeliveryReceipt,
    VendorDeliveryReceiptItem,
    VendorPerformanceLog,
    VendorPurchaseOrder,
    VendorPurchaseOrderItem,
    ZenitionProduct,
)

logger = logging.getLogger(__name__)

# ── File Upload Validation ───────────────────────────────────────────────────
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
ALLOWED_EXCEL_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "text/csv",
}
ALLOWED_EXCEL_EXTENSIONS = {".xlsx", ".xls", ".csv"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_EXCEL_SIZE = 50 * 1024 * 1024  # 50 MB


# Magic-byte signatures for file type verification
_MAGIC_SIGNATURES = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/gif": [b"GIF87a", b"GIF89a"],
    "image/webp": [b"RIFF"],  # RIFF....WEBP
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [b"PK\x03\x04"],  # ZIP-based
    "application/vnd.ms-excel": [b"\xd0\xcf\x11\xe0"],  # OLE2
    "application/pdf": [b"%PDF"],
}

ALLOWED_DOCUMENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "text/csv",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
}
ALLOWED_DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".xlsx",
    ".xls",
    ".csv",
    ".txt",
    ".docx",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
}
MAX_DOCUMENT_SIZE = 50 * 1024 * 1024  # 50 MB


def validate_uploaded_file(uploaded_file, allowed_types, allowed_extensions, max_size):  # noqa: C901, CCR001
    """Validate an uploaded file's content type, extension, size, and magic bytes.

    Returns (is_valid, error_message).
    """
    if not uploaded_file:
        return False, "No file provided"
    if uploaded_file.size > max_size:
        return False, f"File too large. Maximum size is {max_size // (1024 * 1024)} MB."
    # Sanitize filename — strip path components and null bytes
    safe_name = os.path.basename(uploaded_file.name).replace("\x00", "")
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in allowed_extensions:
        return False, f'File type not allowed. Accepted: {", ".join(sorted(allowed_extensions))}'
    if uploaded_file.content_type not in allowed_types:
        return False, f"Invalid file content type: {uploaded_file.content_type}"
    # Magic-byte verification — read first 16 bytes and verify signature
    try:
        header = uploaded_file.read(16)
        uploaded_file.seek(0)  # Reset for downstream consumers
        matched_magic = False
        for mime, signatures in _MAGIC_SIGNATURES.items():
            if mime in allowed_types:
                for sig in signatures:
                    if header.startswith(sig):
                        matched_magic = True
                        break
            if matched_magic:
                break
        # For types without magic signatures (csv, txt), skip magic check
        types_with_magic = set(_MAGIC_SIGNATURES.keys()) & allowed_types
        if types_with_magic and not matched_magic:
            # Only fail if ALL allowed types have magic sigs and none matched
            types_without_magic = allowed_types - set(_MAGIC_SIGNATURES.keys())
            if not types_without_magic:
                return False, "File content does not match its declared type."
    except Exception:
        uploaded_file.seek(0)
    return True, ""


def _parse_json_body(request):
    """Safely parse JSON from request.body.

    Returns (parsed_data, error_response). If error_response is not None, return it directly.
    """
    try:
        return json.loads(request.body), None
    except (json.JSONDecodeError, ValueError):
        return None, JsonResponse({"success": False, "error": "Invalid JSON in request body."}, status=400)


class CustomPasswordChangeView(PasswordChangeView):
    """Custompasswordchangeview."""

    def get_context_data(self, **kwargs):
        """Get context data."""
        context = super().get_context_data(**kwargs)
        context["selected_stream"] = get_default_stream_name(self.request)
        return context


class CustomPasswordChangeDoneView(PasswordChangeDoneView):
    """Custompasswordchangedoneview."""

    template_name = "products/password_change_done.html"

    def get_context_data(self, **kwargs):
        """Get context data."""
        context = super().get_context_data(**kwargs)
        context["selected_stream"] = get_default_stream_name(self.request)
        return context


def _fac_granted(user):
    """Return True if the FeatureAccessMiddleware already authorised this.

    request.  The middleware sets ``user._fac_granted = True`` when the
    Feature Access Control matrix explicitly allows the URL for the user's
    roles, so view-level permission helpers can skip their own checks.
    """
    return getattr(user, "_fac_granted", False)


def is_admin(user):
    """Is admin."""
    if _fac_granted(user):
        return True
    if hasattr(user, "custom_profile"):
        return user.custom_profile.is_admin()
    return user.is_superuser


def is_super_admin(user):
    """Is super admin."""
    if _fac_granted(user):
        return True
    if hasattr(user, "custom_profile"):
        return user.custom_profile.is_super_admin()
    return user.is_superuser


def is_app_admin(user):
    """Is app admin."""
    if _fac_granted(user):
        return True
    if hasattr(user, "custom_profile"):
        return user.custom_profile.is_app_admin()
    return user.is_superuser


def is_lab_incharge(user):
    """Is lab incharge."""
    if _fac_granted(user):
        return True
    if hasattr(user, "custom_profile"):
        return user.custom_profile.is_lab_incharge()
    return user.is_superuser


def can_manage_users(user):
    """Can manage users."""
    if _fac_granted(user):
        return True
    if hasattr(user, "custom_profile"):
        return user.custom_profile.can_manage_users()
    return user.is_superuser


def can_manage_system_allocation(user):
    """Can manage system allocation."""
    return user.is_authenticated


def can_edit_products(user):
    """Can edit products."""
    if _fac_granted(user):
        return True
    if hasattr(user, "custom_profile"):
        return user.custom_profile.can_edit_products()
    return user.is_superuser


def can_delete_products(user):
    """Can delete products."""
    if _fac_granted(user):
        return True
    if hasattr(user, "custom_profile"):
        return user.custom_profile.can_delete_products()
    return user.is_superuser


def can_view_analytics(user):
    """Can view analytics."""
    if _fac_granted(user):
        return True
    if hasattr(user, "custom_profile"):
        return user.custom_profile.can_view_analytics()
    return user.is_superuser


def can_access_waste(user):
    """Lab Incharge, Super Admin, and App Admin can access waste management."""
    if _fac_granted(user):
        return True
    if user.is_superuser:
        return True
    if hasattr(user, "custom_profile"):
        return user.custom_profile.user_roles.filter(role__in=["lab_incharge", "super_admin", "app_admin"]).exists()
    return False


def can_access_tld_badges(user):
    """Lab Incharge, Super Admin, and App Admin can access TLD badge management."""
    if _fac_granted(user):
        return True
    if user.is_superuser:
        return True
    if hasattr(user, "custom_profile"):
        return user.custom_profile.user_roles.filter(role__in=["lab_incharge", "super_admin", "app_admin"]).exists()
    return False


def _get_role_level(user):
    """Return the hierarchy index for *user* (lower = higher privilege).

    Uses the explicit roles first; falls back to is_superuser → 0
    only when the user holds no roles.
    """
    if hasattr(user, "custom_profile") and user.custom_profile:
        return user.custom_profile.highest_role_index()
    if user.is_superuser:
        return 0
    return len(CustomUser._ROLE_HIERARCHY)


def _is_app_admin_user(user):
    """Return True if *user* actually holds the app_admin role (exempt from hierarchy cap).

    Unlike ``CustomUser.is_app_admin()``, this checks the **explicit** role
    assignment — ``is_superuser`` alone does NOT count.
    """
    if hasattr(user, "custom_profile") and user.custom_profile:
        return "app_admin" in user.custom_profile._roles_set
    return False


def get_current_bu(request):
    """Return the BusinessUnit attached to the request by the middleware, or None."""
    return getattr(request, "current_bu", None)


def get_default_stream_name(request):
    """Return the first stream name for the current BU, or 'HIC' as fallback."""
    bu = get_current_bu(request)
    if bu:
        from ..models import Stream  # noqa: F811

        first = (
            Stream.objects.filter(business_unit=bu, is_active=True)
            .order_by("name")
            .values_list("name", flat=True)
            .first()
        )
        if first:
            return first
    return "HIC"


def get_bu_streams(request, user=None):
    """Return a QuerySet of Streams scoped to the current BU *and* the user's.

    stream-level access.  Super-admins see all streams in the BU.

    If no BU is on the request, falls back to the user's globally-accessible
    streams (backward-compatible behaviour).
    """
    from ..models import CustomUser, Stream  # noqa: F401, F811

    bu = get_current_bu(request)
    if user is None:
        user = request.user
    custom_profile, _ = CustomUser.objects.get_or_create(user=user)

    if bu:
        return custom_profile.get_accessible_streams(business_unit=bu).filter(is_active=True)
    else:
        return custom_profile.get_accessible_streams().filter(is_active=True)


def check_user_access(request, stream=None):
    """Check if user has access to the application and specific stream.

    Now also verifies BU-level access when a current BU is set.
    Returns (has_access, error_message, custom_profile)
    """
    custom_profile, created = CustomUser.objects.get_or_create(user=request.user)

    if not request.user.is_superuser and not custom_profile.user_roles.exists():
        error_message = "Access denied. You have no assigned roles. Please contact an administrator."
        return False, error_message, custom_profile

    # ── BU-level gate ────────────────────────────────────────────
    bu = get_current_bu(request)
    if bu and not request.user.is_superuser and not custom_profile.can_access_bu(bu):
        error_message = f"Access denied. You do not have permission to access this Business Unit ({bu})."
        return False, error_message, custom_profile

    # ── Stream-BU gate (applies to ALL users including superusers) ──
    if stream and bu:
        from ..models import Stream as StreamModel

        if not StreamModel.objects.filter(name=stream, business_unit=bu).exists():
            error_message = f'The stream "{stream}" does not belong to the current Business Unit.'
            return False, error_message, custom_profile

    # ── Stream-level access gate (non-superusers only) ──
    if stream and not request.user.is_superuser:
        if not custom_profile.can_access_stream(stream):
            error_message = f"Access denied. You do not have permission to access the {stream} stream."
            return False, error_message, custom_profile

    return True, None, custom_profile


@login_not_required
def home(request):
    """Home."""
    return render(request, "products/home.html")


# ── Business Unit Selection ──


@login_required
def select_bu(request):
    """Show available Business Units and let the user pick one.

    Only BUs the user has explicit access to are shown (super-admins see all).
    The chosen BU id is stored in request.session['selected_bu_id'].
    """
    from ..models import BusinessUnit  # noqa: F811

    custom_profile, _ = CustomUser.objects.get_or_create(user=request.user)
    bus = custom_profile.get_accessible_bus()
    next_url = request.GET.get("next", request.POST.get("next", ""))

    if request.method == "POST":
        bu_id = request.POST.get("bu_id")
        if bu_id:
            try:
                bu = bus.get(id=bu_id)
                request.session["selected_bu_id"] = bu.id
                request.session["selected_bu_name"] = bu.name
                request.session["selected_bu_code"] = bu.slug
                import re as _re

                target = next_url or "/dashboard/"
                target = _re.sub(r"^/bu/[^/]+", "", target)
                if not target.startswith("/"):
                    target = "/" + target
                return redirect(f"/bu/{bu.slug}{target}")
            except BusinessUnit.DoesNotExist:
                return render(
                    request,
                    "products/select_bu.html",
                    {
                        "business_units": bus,
                        "next": next_url,
                        "form_error": "Invalid Business Unit selected.",
                    },
                )

    return render(
        request,
        "products/select_bu.html",
        {
            "business_units": bus,
            "next": next_url,
        },
    )


@login_required
def change_bu(request):
    """Allow user to switch to a different BU (clears session and redirects)."""
    request.session.pop("selected_bu_id", None)
    request.session.pop("selected_bu_name", None)
    request.session.pop("selected_bu_code", None)
    return redirect("select_bu")
