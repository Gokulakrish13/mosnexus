from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """
    Template filter to get value from dictionary with string key
    that might contain hyphens or spaces
    """
    return dictionary.get(key)


@register.filter
def can_manage_users(user):
    if hasattr(user, "custom_profile"):
        return user.custom_profile.can_manage_users()
    return user.is_superuser


@register.filter
def can_manage_system_allocation(user):
    if hasattr(user, "custom_profile"):
        return user.custom_profile.can_manage_system_allocation()
    return user.is_superuser


@register.filter
def can_edit_products(user):
    if hasattr(user, "custom_profile"):
        return user.custom_profile.can_edit_products()
    return user.is_superuser


@register.filter
def can_delete_products(user):
    if hasattr(user, "custom_profile"):
        return user.custom_profile.can_delete_products()
    return user.is_superuser


@register.filter
def can_view_analytics(user):
    if hasattr(user, "custom_profile"):
        return user.custom_profile.can_view_analytics()
    return user.is_superuser


@register.filter
def is_admin(user):
    if hasattr(user, "custom_profile"):
        return user.custom_profile.is_admin()
    return user.is_superuser


@register.filter
def is_super_admin(user):
    if hasattr(user, "custom_profile"):
        return user.custom_profile.is_super_admin()
    return user.is_superuser


@register.filter
def is_app_admin(user):
    if hasattr(user, "custom_profile"):
        return user.custom_profile.is_app_admin()
    return user.is_superuser


@register.filter
def outranks(request_user, target_user):
    """True if request_user has strictly higher privilege than target_user.

    Application Admins are exempt — they outrank everyone (except themselves).
    """
    if request_user == target_user:
        return False
    from products.models import CustomUser

    hierarchy = CustomUser._ROLE_HIERARCHY

    def _level(u):
        if hasattr(u, "custom_profile") and u.custom_profile:
            return u.custom_profile.highest_role_index()
        if u.is_superuser:
            return 0
        return len(hierarchy)

    # app_admin (explicit role, not just is_superuser) bypasses the hierarchy cap
    if (
        hasattr(request_user, "custom_profile")
        and request_user.custom_profile
        and "app_admin" in request_user.custom_profile._roles_set
    ):
        return True
    return _level(request_user) < _level(target_user)


@register.filter
def is_lab_incharge(user):
    if hasattr(user, "custom_profile"):
        return user.custom_profile.is_lab_incharge()
    return user.is_superuser


@register.filter
def has_role(user, role):
    if hasattr(user, "custom_profile") and user.custom_profile:
        return user.custom_profile.user_roles.filter(role=role).exists()
    return False


@register.filter
def has_stream_access(user, stream):
    if hasattr(user, "custom_profile") and user.custom_profile:
        return user.custom_profile.stream_access.filter(stream=stream).exists()
    return False


@register.filter
def user_roles(user):
    if hasattr(user, "custom_profile") and user.custom_profile:
        return user.custom_profile.user_roles.all()
    return []


@register.filter
def user_stream_access(user):
    if hasattr(user, "custom_profile") and user.custom_profile:
        return user.custom_profile.stream_access.all()
    return []


@register.filter
def abs_value(value):
    try:
        return abs(int(value))
    except (ValueError, TypeError):
        return value


@register.filter
def feature_allowed(url_name, request):
    """Return True if the current user may access the given URL name.

    Uses the FAC_ALLOWED_URLS set built by the feature_access_context
    context processor.  URL names NOT governed by any Feature are
    always allowed (returns True).

    Usage:  {% if 'faq'|feature_allowed:request %}
    """
    # Check if this URL name is governed by any Feature
    from products.middleware import FeatureAccessMiddleware

    if not FeatureAccessMiddleware._cache_built:
        FeatureAccessMiddleware._build_cache()

    if url_name not in FeatureAccessMiddleware._url_feature_cache:
        # Not governed — always allowed
        return True

    allowed = getattr(request, "FAC_ALLOWED_URLS", None)
    if allowed is None:
        # Context processor didn't run (standalone template) — fall back
        allowed = request.__dict__.get("FAC_ALLOWED_URLS", set())
    return url_name in allowed


@register.filter
def timesince_days(value):
    """
    Return the number of days until a date (positive) or days past (negative).
    Positive means days remaining, negative means days overdue.
    """
    from datetime import date, datetime

    if not value:
        return None

    try:
        if isinstance(value, datetime):
            target_date = value.date()
        elif isinstance(value, date):
            target_date = value
        else:
            return None

        today = date.today()
        delta = (target_date - today).days
        return delta
    except (ValueError, TypeError, AttributeError):
        return None
