from django.utils.deprecation import MiddlewareMixin
from django.shortcuts import redirect
from django.utils import timezone
from .models import UsageTracking

class NoCacheMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        
        # Role-based access control
        if request.user.is_authenticated and not request.user.is_superuser:
            # Skip for certain paths that should always be accessible
            allowed_paths = ['/login/', '/logout/', '/register/', '/please_login/', '/', '/static/', '/admin/', '/accounts/']
            
            # Check if current path should be skipped
            should_skip = any(request.path.startswith(path) for path in allowed_paths)
            
            if not should_skip:
                # Get or create user's custom profile
                from .models import CustomUser
                try:
                    custom_profile = request.user.custom_profile
                except AttributeError:
                    custom_profile, created = CustomUser.objects.get_or_create(user=request.user)
                    
                # Check if user has any roles
                if not custom_profile.user_roles.exists():
                    from django.contrib.auth import logout
                    from django.contrib import messages
                    logout(request)
                    messages.error(request, 'Access denied. You have no assigned roles. Please contact an administrator.')
                    return redirect('/please_login/')
                    
                # Check stream-specific access for stream-based URLs
                if '/stream/' in request.path:
                    path_parts = request.path.split('/')
                    try:
                        stream_index = path_parts.index('stream')
                        if stream_index + 1 < len(path_parts):
                            stream_name = path_parts[stream_index + 1]
                            
                            # Check if user has access to this stream
                            if not custom_profile.can_access_stream(stream_name):
                                from django.contrib.auth import logout
                                from django.contrib import messages
                                logout(request)
                                messages.error(request, f'Access denied. You do not have permission to access the {stream_name} stream.')
                                return redirect('/please_login/')
                    except (ValueError, IndexError):
                        pass
        
        # If user is not authenticated and accessing a protected HTML page, redirect to please_login
        allowed_paths = ['/login/', '/register/', '/please_login/', '/']
        
        # Allow public access to product detail pages (QR code scanning)
        # Pattern: /stream/<stream_name>/products/<product_id>/
        is_product_detail = '/stream/' in request.path and '/products/' in request.path and request.path.count('/') >= 4
        
        if (not request.user.is_authenticated and
            response.get('Content-Type', '').startswith('text/html') and
            request.path not in allowed_paths and
            not is_product_detail):
            return redirect('/please_login/')
        return response

class UsageTrackingMiddleware(MiddlewareMixin):
    def process_request(self, request):
        # Skip tracking for static files, admin pages, and AJAX requests
        if (request.path.startswith('/static/') or
            request.path.startswith('/admin/') or
            request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest' or
            request.path.startswith('/usage-tracking-data/')):  # Avoid tracking API calls to prevent loops
            return None
        
        # Only track GET requests that return HTML pages
        if request.method == 'GET' and request.user.is_authenticated:
            # Try to get a friendly page name from the URL
            page_name = self.get_page_name(request.path)
            
            UsageTracking.objects.create(
                user=request.user,
                page_name=page_name,
                page_url=request.path,
                session_id=request.session.session_key,
                ip_address=self.get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')
            )
        return None
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
        
    def get_page_name(self, path):
        """
        Convert a URL path to a more readable page name
        """
        if path == '/' or path == '':
            return 'Home'
            
        # Remove trailing slash
        if path.endswith('/'):
            path = path[:-1]
            
        # Remove leading slash
        if path.startswith('/'):
            path = path[1:]
            
        # Handle stream-specific paths
        parts = path.split('/')
        if parts and parts[0] == 'stream' and len(parts) >= 3:
            stream = parts[1]
            page_type = parts[2]
            
            # Special handling for common stream pages
            if page_type == 'products':
                return f"{stream} Products"
            elif page_type == 'categories':
                return f"{stream} Categories"
            elif page_type == 'dashboard':
                return f"{stream} Dashboard"
            elif page_type == 'location':
                return f"{stream} Locations"
            elif page_type == 'system-allocation':
                return f"{stream} System Allocation"
                
        # Replace dashes and underscores with spaces
        page_name = path.replace('-', ' ').replace('_', ' ')
        
        # Capitalize words
        page_name = ' '.join(word.capitalize() for word in page_name.split())
        
        return page_name

# Session tracking middleware for dashboard
class SessionTrackingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        
        # Update user session if authenticated
        if request.user.is_authenticated and hasattr(request, 'session'):
            session_key = request.session.session_key
            if session_key:
                from .models import UserSession
                from django.utils import timezone
                
                # Get client IP
                x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
                if x_forwarded_for:
                    ip = x_forwarded_for.split(',')[0]
                else:
                    ip = request.META.get('REMOTE_ADDR')
                
                # Update or create session record
                session_obj, created = UserSession.objects.get_or_create(
                    session_key=session_key,
                    defaults={
                        'user': request.user,
                        'ip_address': ip,
                        'user_agent': request.META.get('HTTP_USER_AGENT', '')
                    }
                )
                
                if not created:
                    session_obj.last_activity = timezone.now()
                    session_obj.user = request.user  # Update user in case of session reuse
                    session_obj.save()
        
        return response
