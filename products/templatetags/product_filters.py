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
    """Check if user can manage other users"""
    if hasattr(user, 'custom_profile'):
        return user.custom_profile.can_manage_users()
    return user.is_superuser

@register.filter
def can_manage_system_allocation(user):
    """Check if user can manage system allocation"""
    if hasattr(user, 'custom_profile'):
        return user.custom_profile.can_manage_system_allocation()
    return user.is_superuser

@register.filter
def can_edit_products(user):
    """Check if user can edit products"""
    if hasattr(user, 'custom_profile'):
        return user.custom_profile.can_edit_products()
    return user.is_superuser

@register.filter
def can_delete_products(user):
    """Check if user can delete products"""
    if hasattr(user, 'custom_profile'):
        return user.custom_profile.can_delete_products()
    return user.is_superuser

@register.filter
def can_view_analytics(user):
    """Check if user can view analytics"""
    if hasattr(user, 'custom_profile'):
        return user.custom_profile.can_view_analytics()
    return user.is_superuser

@register.filter
def is_admin(user):
    """Check if user is admin"""
    if hasattr(user, 'custom_profile'):
        return user.custom_profile.is_admin()
    return user.is_superuser

@register.filter
def is_super_admin(user):
    """Check if user is super admin"""
    if hasattr(user, 'custom_profile'):
        return user.custom_profile.is_super_admin()
    return user.is_superuser

@register.filter
def is_lab_incharge(user):
    """Check if user is lab incharge"""
    if hasattr(user, 'custom_profile'):
        return user.custom_profile.is_lab_incharge()
    return user.is_superuser

@register.filter
def has_role(user, role):
    """Check if user has a specific role"""
    if hasattr(user, 'custom_profile') and user.custom_profile:
        return user.custom_profile.user_roles.filter(role=role).exists()
    return False

@register.filter
def has_stream_access(user, stream):
    """Check if user has access to a specific stream"""
    if hasattr(user, 'custom_profile') and user.custom_profile:
        return user.custom_profile.stream_access.filter(stream=stream).exists()
    return False

@register.filter
def user_roles(user):
    """Get all roles for a user"""
    if hasattr(user, 'custom_profile') and user.custom_profile:
        return user.custom_profile.user_roles.all()
    return []

@register.filter
def user_stream_access(user):
    """Get all stream access for a user"""
    if hasattr(user, 'custom_profile') and user.custom_profile:
        return user.custom_profile.stream_access.all()
    return []
