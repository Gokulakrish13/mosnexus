"""
NexusOps — Template Context Processors
========================================
Adds global context variables available to every template.
"""

# pylint: disable=broad-exception-caught,import-outside-toplevel,protected-access,too-complex

from inventory.version import RELEASE_CODENAME, RELEASE_DATE, VERSION_INFO, get_full_version, get_version

from django.conf import settings


def version_context(request):
    """
    Inject application version info into every template context.

    Usage in templates:
        {{ APP_VERSION }}           → "1.0.0"
        {{ APP_FULL_VERSION }}      → "1.0.0+prod"
        {{ APP_CODENAME }}          → "NexusOps Enterprise"
        {{ APP_ENVIRONMENT }}       → "Production"
    """
    env_key = VERSION_INFO.get("build", "dev")
    from inventory.version import ENVIRONMENTS

    env_display = ENVIRONMENTS.get(env_key, env_key.title())

    return {
        "APP_VERSION": get_version(),
        "APP_FULL_VERSION": get_full_version(),
        "APP_CODENAME": RELEASE_CODENAME,
        "APP_RELEASE_DATE": RELEASE_DATE,
        "APP_ENVIRONMENT": env_display,
        "APP_ENV_KEY": env_key,
        "NEXUSOPS_DEBUG": getattr(settings, "DEBUG", False),
        "APP_LONG_NAME": "AI-Powered Unified Operations & Resource Management Portal",
    }


def business_unit_context(request):
    """
    Inject the currently-selected Business Unit into every template context.

    Usage in templates:
        {{ SELECTED_BU_ID }}    → 1
        {{ SELECTED_BU_NAME }}  → "Image Guided Therapy – Modality Solutions"
        {{ SELECTED_BU_CODE }}  → "IGT-MoS"
        {{ SELECTED_BU }}       → BusinessUnit instance (or None)
        {{ BU_URL_PREFIX }}     → "/bu/IGT-MoS"
        {{ BU_SHORT }}          → "IGT"          (bu_name field)
        {{ BU_DIVISION }}       → "MoS"          (division field)
        {{ BU_TITLE }}          → "IGT MoS"      (short combo for titles)
        {{ BU_PORTAL_NAME }}    → "IGT MoS Portal" or "NexusOps" fallback
    """
    bu_id = request.session.get("selected_bu_id")
    bu_name = request.session.get("selected_bu_name", "")
    bu_slug = request.session.get("selected_bu_code", "")  # Session key is 'selected_bu_code' but holds the BU slug
    bu_obj = None
    bu_short = ""
    bu_division = ""

    if bu_id:
        # Cache the BU object on the request to avoid repeated DB queries
        # (BusinessUnitURLMiddleware may have already fetched it)
        if hasattr(request, "current_bu") and request.current_bu and request.current_bu.id == bu_id:
            bu_obj = request.current_bu
        else:
            from products.models import BusinessUnit

            try:
                bu_obj = BusinessUnit.objects.get(id=bu_id)
            except BusinessUnit.DoesNotExist:
                pass
        if bu_obj:
            bu_short = bu_obj.bu_name
            bu_division = bu_obj.division

    bu_title = f"{bu_short} {bu_division}".strip() if bu_short else "NexusOps"
    bu_portal_name = f"{bu_title} Portal" if bu_short else "NexusOps"

    return {
        "SELECTED_BU_ID": bu_id,
        "SELECTED_BU_NAME": bu_name,
        "SELECTED_BU_CODE": bu_slug,
        "SELECTED_BU": bu_obj,
        "BU_URL_PREFIX": f"/bu/{bu_slug}" if bu_slug else "",
        "BU_SHORT": bu_short,
        "BU_DIVISION": bu_division,
        "BU_TITLE": bu_title,
        "BU_PORTAL_NAME": bu_portal_name,
        "BU_DEFAULT_STREAM": _get_bu_default_stream(bu_obj),
    }


def _get_bu_default_stream(bu_obj):
    """Return the first active stream name for a given BU, or 'HIC' as fallback."""
    if bu_obj:
        from products.models import Stream

        first = (
            Stream.objects.filter(business_unit=bu_obj, is_active=True)
            .order_by("name")
            .values_list("name", flat=True)
            .first()
        )
        if first:
            return first
    return "HIC"


def site_settings_context(request):
    """
    Inject site-wide settings into every template context.

    Usage in templates:
        {{ DEVTOOLS_PROTECTION }}  → True / False
    """
    # Cache on request object to avoid multiple DB queries per request
    if hasattr(request, "_cached_site_settings"):
        devtools = request._cached_site_settings
    else:
        from products.models import SiteSetting

        try:
            settings_obj = SiteSetting.load()
            devtools = settings_obj.devtools_protection
        except Exception:
            devtools = False
        request._cached_site_settings = devtools

    return {
        "DEVTOOLS_PROTECTION": devtools,
    }


def feature_access_context(request):
    """
    Build a set of URL names the current user is allowed to access,
    based on the Feature Access Control matrix.

    Usage in templates:
        {% if 'faq'|feature_allowed:request %}
            <a href="{% url 'faq' %}">Help & FAQ</a>
        {% endif %}

    The set is cached on the request object so the DB is hit only once
    per request.
    """
    allowed = set()
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        request.FAC_ALLOWED_URLS = allowed
        return {"FAC_ALLOWED_URLS": allowed}

    # app_admin gets everything
    try:
        cp = user.custom_profile
    except Exception:
        from products.models import CustomUser

        cp, _ = CustomUser.objects.get_or_create(user=user)

    user_roles = cp._roles_set
    if "app_admin" in user_roles:
        # Shortcut — all URL names are allowed
        from products.models import Feature

        for feat in Feature.objects.filter(is_active=True):
            for uname in feat.url_names or []:
                allowed.add(uname)
        request.FAC_ALLOWED_URLS = allowed
        return {"FAC_ALLOWED_URLS": allowed}

    if not user_roles:
        request.FAC_ALLOWED_URLS = allowed
        return {"FAC_ALLOWED_URLS": allowed}

    # Build the allowed set from FeatureRoleAccess
    from products.models import Feature, FeatureRoleAccess

    granted_feature_ids = set(
        FeatureRoleAccess.objects.filter(
            role__in=user_roles,
            has_access=True,
            feature__is_active=True,
        ).values_list("feature_id", flat=True)
    )
    for feat in Feature.objects.filter(id__in=granted_feature_ids, is_active=True):
        for uname in feat.url_names or []:
            allowed.add(uname)

    # Also add URL names that are NOT governed by any Feature (ungated pages)
    from products.middleware import FeatureAccessMiddleware

    if not FeatureAccessMiddleware._cache_built:
        FeatureAccessMiddleware._build_cache()
    # ungated urls are those not in the cache — they're always allowed
    # (we don't add them to allowed set because the filter defaults to True for ungated)

    # Cache on request so template filter can access it
    request.FAC_ALLOWED_URLS = allowed
    return {"FAC_ALLOWED_URLS": allowed}
