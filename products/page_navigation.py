"""
Page Navigation — Global back/forward + breadcrumb toolbar
==========================================================
Tracks which pages the user visits in session-stored stacks,
and generates hierarchical breadcrumbs from the current URL.

Components
──────────
• PageNavigationMiddleware  — records visit history on every GET
• page_navigation_context   — context processor exposing data to templates

Data structures
───────────────
• back_stack / forward_stack : lists used as stacks (browser semantics)
• breadcrumbs                : derived from URL path (stateless, no history)
"""

# pylint: disable=broad-exception-caught,invalid-name,too-complex,too-many-return-statements

from __future__ import annotations

import re

from django.urls import resolve

# ─── URL → human label mapping ───────────────────────────────────────────────

# Friendly labels for known URL segments.  Order doesn't matter — segments are
# looked up individually while building breadcrumbs.
_SEGMENT_LABELS: dict[str, str] = {
    "dashboard": "Dashboard",
    "stream": "Streams",
    "products": "Products",
    "categories": "Categories",
    "location": "Locations",
    "system-allocation": "System Allocation",
    "allocation-tree": "Allocation Tree",
    "subleveldata": "Sub-Level Data",
    "subleveltools": "Sub-Level Tools",
    "booking": "Booking Hub",
    "downtime": "Downtime",
    "build-servers": "Build Servers",
    "floors": "Floors",
    "operating-systems": "Operating Systems",
    "recurring-reservations": "Recurring Reservations",
    "reservation-instances": "Reservation Instances",
    "waitlist": "Waitlist",
    "utilization": "Utilization",
    "conflicts": "Conflicts",
    "calibration": "Calibration",
    "compliance": "Compliance",
    "requirements": "Requirements",
    "checklists": "Checklists",
    "alerts": "Alerts",
    "documents": "Documents",
    "lifecycle": "Asset Lifecycle",
    "maintenance-calendar": "Maintenance Calendar",
    "inventory-alerts": "Inventory Alerts",
    "thresholds": "Thresholds",
    "versions": "Versions",
    "holistic-dashboard": "Holistic Dashboard",
    "analytics_dashboard": "Analytics",
    "notes": "Notes",
    "projects": "Projects",
    "manage-streams": "Manage Streams",
    "users": "Users",
    "faq": "FAQ",
    "feature-hub": "Feature Hub",
    "audit-log": "Audit Log",
    "personal_trackboard": "Personal Trackboard",
    "usage-tracking": "Usage Tracking",
    "build_os_info": "Build & OS Info",
    "reservations": "Reservations Hub",
    "ai": "AI Features",
    "calibration-reports": "AI Calibration",
    "ocr": "AI Document OCR",
    "nl-dashboard": "AI NL Query",
    "inventory-forecast": "AI Forecast",
    "smart-scheduler": "AI Scheduler",
    "model-management": "AI Models",
    "usage-analytics": "Usage Analytics",
    "anomaly-detection": "Anomaly Detection",
    "tld-badges": "TLD Badges",
    "support": "Support Tickets",
    "live-support": "Live Support",
    "admin-queue": "Admin Queue",
    "shift-handover": "Shift Handover",
    "waste-management": "Waste Management",
    "add": "Add",
    "edit": "Edit",
    "create": "Create",
    "delete": "Delete",
    "export": "Export",
    "detail": "Detail",
}

# Paths to skip tracking (AJAX / API / static / media)
_SKIP_PREFIXES = (
    "/api/",
    "/static/",
    "/media/",
    "/admin/",
    "/usage-tracking-data/",
)

_SKIP_PATTERNS = re.compile(r"\.(js|css|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot|map)$", re.I)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _label_for_segment(segment: str) -> str:
    """Return a human-readable label for a URL segment."""
    # Known mapping?
    if segment in _SEGMENT_LABELS:
        return _SEGMENT_LABELS[segment]
    # Looks like an integer ID → #123
    if segment.isdigit():
        return f"#{segment}"
    # If segment is all uppercase (e.g. stream names like PIC, MOS), keep as-is
    if segment.isupper():
        return segment
    # Fallback: capitalise and replace dashes/underscores
    return segment.replace("-", " ").replace("_", " ").title()


def _page_title_for_path(path: str) -> str:
    """Best-effort page title from the URL path."""
    try:
        match = resolve(path)
        # Use the URL pattern name as a fallback title
        if match.url_name:
            return match.url_name.replace("_", " ").replace("-", " ").title()
    except Exception:
        pass
    parts = [p for p in path.strip("/").split("/") if p]
    if parts:
        return _label_for_segment(parts[-1])
    return "Home"


def build_breadcrumbs(path: str, bu_prefix: str = "") -> list[dict[str, str]]:
    """
    Build a breadcrumb trail from *path*.

    Returns a list of ``{"label": "…", "url": "/…/"}`` dicts.
    Always starts with Home (``/dashboard/``).

    *bu_prefix* is prepended to every URL so breadcrumb links stay inside
    the active Business-Unit scope (e.g. ``"/bu/IGT-MoS"``).
    """
    crumbs: list[dict[str, str]] = [{"label": "Home", "url": f"{bu_prefix}/dashboard/", "icon": "fa-home"}]

    clean = path.strip("/")
    if not clean or clean == "dashboard":
        # We're on the home page
        if clean == "dashboard":
            crumbs[-1]["active"] = True  # type: ignore[assignment]
        return crumbs

    # Pages that logically live under FAQ — inject FAQ as parent crumb
    _FAQ_CHILDREN = ("support", "live-support")
    if any(clean == prefix or clean.startswith(prefix + "/") for prefix in _FAQ_CHILDREN):
        crumbs.append({"label": "FAQ", "url": f"{bu_prefix}/faq/", "icon": "fa-question-circle"})

    parts = clean.split("/")
    accumulated = ""

    for i, part in enumerate(parts):
        accumulated += f"/{part}"
        url = f"{bu_prefix}{accumulated}/"
        label = _label_for_segment(part)

        # If the segment is "stream" and the next segment is the stream name,
        # skip the literal "stream" segment — just show the stream name.
        if part == "stream":
            continue

        # "live-support" is a prefix with no standalone view — collapse it
        # so crumbs link to the actual page, not the bare prefix.
        if part == "live-support":
            continue

        # If previous segment was "stream", this *is* the stream name.
        # Point the crumb to the BU dashboard (bare /stream/<name>/
        # has no route).
        icon = ""
        if i > 0 and parts[i - 1] == "stream":
            label = part.upper()  # e.g. "HIC"
            icon = "fa-code-branch"
            url = f"{bu_prefix}/dashboard/"

        crumb = {"label": label, "url": url}
        if icon:
            crumb["icon"] = icon

        crumbs.append(crumb)

    # Mark the last crumb as active
    if crumbs:
        crumbs[-1]["active"] = True  # type: ignore[assignment]

    return crumbs


# ─── Middleware ────────────────────────────────────────────────────────────────


class PageNavigationMiddleware:
    """
    Tracks page-level back/forward history in the session.

    Session keys:
        page_nav_back     – list[str]  back-stack of URLs
        page_nav_fwd      – list[str]  forward-stack of URLs
        page_nav_current  – str        current URL
    """

    MAX_STACK = 50  # cap each stack to avoid unbounded session growth

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Only track navigable GET pages for authenticated users
        if request.method != "GET":
            return response
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            return response

        path = request.path
        content_type = response.get("Content-Type", "")

        # Skip non-HTML, API, static, AJAX
        if not content_type.startswith("text/html"):
            return response
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return response
        if _SKIP_PATTERNS.search(path):
            return response
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return response
        # Skip redirects
        if 300 <= response.status_code < 400:
            return response

        # --- Read stacks from session ---
        back = request.session.get("page_nav_back", [])
        fwd = request.session.get("page_nav_fwd", [])
        current = request.session.get("page_nav_current", "")

        # If this is a nav action (?_nav=back / ?_nav=forward) skip recording
        nav_action = request.GET.get("_nav")
        if nav_action:
            return response

        # --- Record navigation ---
        if current and current != path:
            back.append(current)
            if len(back) > self.MAX_STACK:
                back = back[-self.MAX_STACK :]
            fwd.clear()  # new navigation kills forward history

        request.session["page_nav_back"] = back
        request.session["page_nav_fwd"] = fwd
        request.session["page_nav_current"] = path

        return response


# ─── Context processor ────────────────────────────────────────────────────────


def page_navigation_context(request):
    """
    Inject page navigation data into every template.

    Available in templates:
        {{ page_nav_breadcrumbs }}   – list of breadcrumb dicts
        {{ page_nav_can_back }}      – bool
        {{ page_nav_can_forward }}   – bool
        {{ page_nav_back_url }}      – str | ""
        {{ page_nav_forward_url }}   – str | ""
        {{ page_nav_current }}       – str  current path
    """
    path = request.path

    # Derive the BU prefix so breadcrumb URLs stay inside the active BU scope.
    # BusinessUnitURLMiddleware stores the BU slug on request.current_bu_code.
    bu_code = getattr(request, "current_bu_code", None)
    bu_prefix = f"/bu/{bu_code}" if bu_code else ""

    back = request.session.get("page_nav_back", [])
    fwd = request.session.get("page_nav_fwd", [])

    return {
        "page_nav_breadcrumbs": build_breadcrumbs(path, bu_prefix=bu_prefix),
        "page_nav_can_back": len(back) > 0,
        "page_nav_can_forward": len(fwd) > 0,
        "page_nav_back_url": back[-1] if back else "",
        "page_nav_forward_url": fwd[-1] if fwd else "",
        "page_nav_current": path,
    }
