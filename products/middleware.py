# pylint: disable=broad-exception-caught,import-outside-toplevel,invalid-name,logging-fstring-interpolation,missing-class-docstring,missing-function-docstring,no-else-return,too-complex,too-many-lines,too-many-return-statements,unused-argument,unused-variable
import atexit
import html as html_module
import json
import logging
import re
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings as django_settings
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from django.utils.http import url_has_allowed_host_and_scheme, urlencode

from .models import UsageTracking

logger = logging.getLogger(__name__)


class LoginRateLimitMiddleware(MiddlewareMixin):
    """
    Application-level brute-force protection for the login endpoint.
    Tracks failed login attempts per IP and locks out after MAX_ATTEMPTS
    within the WINDOW period.

    Settings (in settings.py):
        LOGIN_RATELIMIT_MAX_ATTEMPTS = 5   # Max failed attempts
        LOGIN_RATELIMIT_WINDOW = 300       # Window in seconds (5 min)
        LOGIN_RATELIMIT_LOCKOUT = 900      # Lockout duration in seconds (15 min)
    """

    # In-memory store: {ip: [(timestamp, success), ...]}  — protected by _lock
    _attempts: dict[str, list[tuple[object, bool]]] = defaultdict(list)  # type: ignore[assignment]
    _lock = threading.Lock()

    def process_request(self, request):
        if request.path != "/login/" or request.method != "POST":
            return None

        ip = self._get_client_ip(request)
        max_attempts = getattr(django_settings, "LOGIN_RATELIMIT_MAX_ATTEMPTS", 5)
        window = getattr(django_settings, "LOGIN_RATELIMIT_WINDOW", 300)
        lockout = getattr(django_settings, "LOGIN_RATELIMIT_LOCKOUT", 900)
        now = timezone.now()

        with self._lock:
            # Clean old entries outside window + lockout
            cutoff = now - timedelta(seconds=max(window, lockout))
            self._attempts[ip] = [(ts, ok) for ts, ok in self._attempts[ip] if ts > cutoff]

            # Periodic sweep: remove IPs with no entries to prevent memory leak
            if len(self._attempts) > 1000:
                stale_ips = [k for k, v in self._attempts.items() if not v]
                for k in stale_ips:
                    del self._attempts[k]

            # Count recent failures
            recent_failures = sum(1 for ts, ok in self._attempts[ip] if not ok and ts > now - timedelta(seconds=window))

            if recent_failures >= max_attempts:
                # Check if lockout has passed since last failure
                last_failure = max((ts for ts, ok in self._attempts[ip] if not ok), default=now)
                if now < last_failure + timedelta(seconds=lockout):
                    remaining = int((last_failure + timedelta(seconds=lockout) - now).total_seconds())
                    logger.warning(f"Login rate limit exceeded for IP {ip}")
                    from django.contrib import messages as _msgs

                    _msgs.error(
                        request, f"Too many failed login attempts. Please try again in {remaining // 60 + 1} minute(s)."
                    )
                    return redirect("/login/")

        return None

    def process_response(self, request, response):
        if request.path != "/login/" or request.method != "POST":
            return response

        ip = self._get_client_ip(request)
        now = timezone.now()

        # Determine if login succeeded: if response redirects away from /login/
        # (successful login redirects to /select-bu/ or /dashboard/)
        success = response.status_code in (301, 302) and "/login/" not in response.get("Location", "/login/")

        with self._lock:
            self._attempts[ip].append((now, success))

            # On success, clear failure history for this IP
            if success:
                self._attempts[ip] = [(now, True)]

        return response

    @staticmethod
    def _get_client_ip(request):
        """
        Extract client IP. Uses the last entry in X-Forwarded-For (closest proxy)
        when behind a trusted proxy, otherwise falls back to REMOTE_ADDR.
        Validates the IP format to prevent spoofing.
        """
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            # Use the rightmost IP (last proxy hop before our trusted reverse proxy)
            # This is harder to spoof than the leftmost (client-provided) entry
            parts = [ip.strip() for ip in x_forwarded_for.split(",")]
            # If behind a single proxy, use the first entry; for multiple proxies
            # the last entry before our own proxy is the real client IP
            client_ip = parts[0].strip() if len(parts) == 1 else parts[-1].strip()

            # Validate IPv4 or IPv6 format
            if re.match(r"^(\d{1,3}\.){3}\d{1,3}$", client_ip) or ":" in client_ip:
                return client_ip
        return request.META.get("REMOTE_ADDR", "")


class MaintenanceMiddleware(MiddlewareMixin):
    """
    Middleware that checks for a maintenance flag file (JSON).
    When the file exists, all requests (except from superusers and bypass IPs)
    get a 503 Service Unavailable maintenance page with an optional countdown timer.

    Toggle with:  python manage.py maintenance --on
                  python manage.py maintenance --on --duration 3d
                  python manage.py maintenance --off
    """

    def process_request(self, request):
        flag_file = getattr(
            django_settings, "MAINTENANCE_MODE_FLAG_FILE", django_settings.BASE_DIR / "maintenance.flag"
        )
        flag_path = Path(flag_file)

        # Check if the flag file exists → maintenance is ON
        if not flag_path.exists():
            return None  # Not in maintenance mode, continue normally

        # --- Parse the flag file (JSON or legacy plain text) ---
        try:
            raw = flag_path.read_text(encoding="utf-8").strip()
            data = json.loads(raw)
        except Exception:
            # Legacy plain-text flag file
            data = {"message": raw if raw else ""}

        # --- Check if maintenance has expired ---
        end_time_str = data.get("end_time")
        end_time = None
        if end_time_str:
            try:
                end_time = datetime.fromisoformat(end_time_str)
                if timezone.is_naive(end_time):
                    end_time = timezone.make_aware(end_time)
                if timezone.now() >= end_time:
                    # Duration expired → auto-disable maintenance
                    flag_path.unlink(missing_ok=True)
                    return None
            except (ValueError, TypeError):
                end_time = None

        # --- Allow admin site so superusers can still log in ---
        if request.path.startswith("/admin/"):
            return None

        # --- Allow static / media files ---
        if request.path.startswith(("/static/", "/media/")):
            return None

        # --- Allow superusers through ---
        if hasattr(request, "user") and request.user.is_authenticated and request.user.is_superuser:
            return None

        # --- Allow bypass IPs (e.g. localhost during development) ---
        bypass_ips = getattr(django_settings, "MAINTENANCE_BYPASS_IPS", [])
        client_ip = self._get_client_ip(request)
        if client_ip in bypass_ips:
            return None

        # --- Build context for the template ---
        message = data.get("message", "")
        context = {
            "maintenance_message": message
            or "We are currently performing scheduled maintenance. Please check back soon.",
            "end_time_iso": end_time.isoformat() if end_time else "",
            "has_timer": end_time is not None,
        }

        # Render the maintenance template
        try:
            html = render_to_string("products/maintenance.html", context)
        except Exception:
            timer_html = ""
            if end_time:
                timer_html = f'<p>Estimated end: {html_module.escape(end_time.strftime("%b %d, %Y %I:%M %p"))}</p>'
            safe_message = html_module.escape(
                message or "We are currently performing scheduled maintenance. Please check back soon."
            )
            html = (
                "<html><head><title>Under Maintenance</title></head>"
                '<body style="font-family:sans-serif;text-align:center;padding:80px;">'
                "<h1>\U0001f527 Under Maintenance</h1>"
                f"<p>{safe_message}</p>"
                f"{timer_html}"
                "</body></html>"
            )

        return HttpResponse(html, status=503, content_type="text/html")

    @staticmethod
    def _get_client_ip(request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")


class BusinessUnitURLMiddleware:
    """
    URL-based Business-Unit routing.

    URLs under ``/bu/<code>/…`` are scoped to a specific BU:
      • The BU code is extracted, validated against the DB, and stored on
        ``request.current_bu`` / ``request.session``.
      • ``request.path_info`` is rewritten (the ``/bu/<code>`` prefix stripped)
        so existing URL patterns match without modification.
      • ``set_script_prefix('/bu/<code>/')`` makes Django's ``reverse()`` and
        the ``{% url %}`` template tag automatically produce BU-prefixed URLs.

    Authenticated users who hit a non-BU, non-exempt URL are redirected to
    ``/bu/<code>/…`` (if a BU is already in session) or to ``/select-bu/``.
    """

    EXEMPT_PREFIXES = (
        "/login/",
        "/logout/",
        "/register/",
        "/please_login/",
        "/select-bu/",
        "/change-bu/",
        "/manage-business-units/",
        "/admin/",
        "/static/",
        "/media/",
        "/api/health/",
        "/api/version/",
        "/api/demo-request/submit/",
        "/api/vulnerability-report/submit/",
    )
    EXEMPT_EXACT = ("/", "")
    BU_RE = re.compile(r"^/bu/([^/]+)(/.*)?$")

    def __init__(self, get_response):
        self.get_response = get_response

    # ------------------------------------------------------------------ #
    def __call__(self, request):
        from django.urls import set_script_prefix

        match = self.BU_RE.match(request.path_info)

        if match:
            # ── URL starts with /bu/<code>/ ──────────────────────────
            bu_code = match.group(1)
            remaining = match.group(2) or "/"

            from products.models import BusinessUnit

            try:
                bu = BusinessUnit.objects.get(slug=bu_code, is_active=True)
            except BusinessUnit.DoesNotExist as exc:
                raise Http404(f'Business Unit "{bu_code}" not found.') from exc

            # ── Enforce BU-level access (all users, including superusers) ─────────
            user = getattr(request, "user", None)
            if user and user.is_authenticated:
                from products.models import CustomUser

                try:
                    cp = user.custom_profile
                except Exception:
                    cp, _ = CustomUser.objects.get_or_create(user=user)
                if not cp.can_access_bu(bu):
                    from django.contrib import messages as _msgs

                    _msgs.error(
                        request,
                        f"Access denied — you do not have permission to access "
                        f'the "{bu}" Business Unit. Please select a Business Unit '
                        f"you have been granted access to, or contact your "
                        f"administrator to request access.",
                    )
                    return redirect("/select-bu/")

            # Expose BU on the request object
            request.current_bu = bu
            request.current_bu_code = bu.slug

            # Persist in session (so other code can read it)
            if hasattr(request, "session"):
                request.session["selected_bu_id"] = bu.id
                request.session["selected_bu_name"] = bu.name
                request.session["selected_bu_code"] = bu.slug

            # Rewrite paths so Django's URL resolver sees the original patterns
            request.path_info = remaining
            request.path = remaining
            request.META["PATH_INFO"] = remaining

            # Make reverse() / {% url %} prepend the BU prefix automatically
            set_script_prefix(f"/bu/{bu_code}/")

        elif self._is_exempt(request):
            # ── Exempt path — let it through ─────────────────────────
            pass

        elif getattr(request, "user", None) and request.user.is_authenticated:
            # ── Authenticated user on a plain (non-BU) URL ───────────
            bu_code = getattr(request, "session", {}).get("selected_bu_code")
            if bu_code:
                # They already chose a BU — bounce to the BU-prefixed URL
                return redirect(f"/bu/{bu_code}{request.get_full_path()}")
            else:
                # No BU yet — send to the selection page
                next_url = request.get_full_path()
                return redirect(f"/select-bu/?next={next_url}")

        response = self.get_response(request)
        return response

    # ------------------------------------------------------------------ #
    def _is_exempt(self, request):
        path = request.path_info
        if path in self.EXEMPT_EXACT:
            return True
        return any(path.startswith(p) for p in self.EXEMPT_PREFIXES)


class NoCacheMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        """Enforce RBAC before the view executes — deny access early."""
        if not request.user.is_authenticated or request.user.is_superuser:
            return None

        allowed_paths = [
            "/login/",
            "/logout/",
            "/register/",
            "/please_login/",
            "/",
            "/static/",
            "/phnx-admin-secure/",
            "/accounts/",
        ]
        should_skip = any(request.path.startswith(path) for path in allowed_paths)
        if should_skip:
            return None

        from .models import CustomUser

        try:
            custom_profile = request.user.custom_profile
        except AttributeError:
            custom_profile, created = CustomUser.objects.get_or_create(user=request.user)

        if not custom_profile.user_roles.exists():
            from django.contrib import messages

            messages.error(request, "Access denied. You have no assigned roles. Please contact an administrator.")
            return redirect("/please_login/")

        # Check stream-specific access for stream-based URLs
        if "/stream/" in request.path:
            path_parts = request.path.split("/")
            try:
                stream_index = path_parts.index("stream")
                if stream_index + 1 < len(path_parts):
                    stream_name = path_parts[stream_index + 1]
                    if not custom_profile.can_access_stream(stream_name):
                        from django.contrib import messages

                        messages.error(
                            request, f"Access denied. You do not have permission to access the {stream_name} stream."
                        )
                        return redirect("/select-bu/")
            except (ValueError, IndexError):
                pass

        return None

    def process_response(self, request, response):
        # Skip no-cache headers for static files and WhiteNoise-served assets
        content_type = response.get("Content-Type", "")
        is_static = request.path.startswith("/static/") or content_type.startswith(
            ("image/", "font/", "application/javascript", "text/css")
        )
        if not is_static:
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"

        # If user is not authenticated and accessing a protected HTML page, redirect to please_login
        allowed_paths = ["/login/", "/logout/", "/register/", "/please_login/", "/", "/api/health/"]

        # Allow public access to product detail pages (QR code scanning)
        is_product_detail = False
        if "/stream/" in request.path and "/products/" in request.path:
            is_product_detail = bool(re.match(r"^/stream/[^/]+/products/\d+/$", request.path))

        if (
            not request.user.is_authenticated
            and response.get("Content-Type", "").startswith("text/html")
            and request.path not in allowed_paths
            and not request.path.startswith("/static/")
            and not is_product_detail
        ):
            # Validate the redirect URL to prevent open redirects
            next_url = request.get_full_path()
            if not url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
            ):
                next_url = "/"
            return redirect("/please_login/?" + urlencode({"next": next_url}))
        return response


class UsageTrackingMiddleware(MiddlewareMixin):
    """
    Buffers usage-tracking records in memory and bulk-inserts them
    periodically (every FLUSH_INTERVAL seconds or FLUSH_SIZE records),
    avoiding a DB INSERT on every single page view.
    """

    _buffer: list[dict[str, object]] = []
    _lock = threading.Lock()
    _last_flush = timezone.now()
    FLUSH_INTERVAL = 30  # seconds — flush at least this often
    FLUSH_SIZE = 50  # records — flush when buffer reaches this size

    def process_request(self, request):
        if (
            request.path.startswith("/static/")
            or request.path.startswith("/admin/")
            or request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest"
            or request.path.startswith("/usage-tracking-data/")
        ):  # Avoid tracking API calls to prevent loops
            return None

        # Only track GET requests that return HTML pages
        if request.method == "GET" and request.user.is_authenticated:
            page_name = self.get_page_name(request.path)
            record = UsageTracking(
                user=request.user,
                page_name=page_name,
                page_url=request.path,
                session_id=request.session.session_key,
                ip_address=self.get_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                business_unit=getattr(request, "current_bu", None),
            )
            self._add_to_buffer(record)
        return None

    @classmethod
    def _add_to_buffer(cls, record):
        """Thread-safe append; flush when buffer is full or interval elapsed."""
        with cls._lock:
            cls._buffer.append(record)
            now = timezone.now()
            elapsed = (now - cls._last_flush).total_seconds()
            if len(cls._buffer) >= cls.FLUSH_SIZE or elapsed >= cls.FLUSH_INTERVAL:
                cls._flush_buffer()

    @classmethod
    def _flush_buffer(cls):
        """Bulk-insert buffered records. Caller must hold _lock."""
        if not cls._buffer:
            return
        to_insert = list(cls._buffer)
        cls._buffer.clear()
        cls._last_flush = timezone.now()
        try:
            UsageTracking.objects.bulk_create(to_insert, ignore_conflicts=True)
        except Exception:
            logger.exception(  # pylint: disable=logging-too-many-args
                "Failed to flush UsageTracking buffer (%d records)",
                len(to_insert),
            )

    @classmethod
    def flush_on_shutdown(cls):
        """Called at interpreter exit to persist any remaining records."""
        with cls._lock:
            cls._flush_buffer()

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip = x_forwarded_for.split(",")[0]
        else:
            ip = request.META.get("REMOTE_ADDR")
        return ip

    def get_page_name(self, path):
        """
        Convert a URL path to a more readable page name
        """
        if path in ("/", ""):
            return "Home"

        if path.endswith("/"):
            path = path[:-1]

        if path.startswith("/"):
            path = path[1:]

        # Handle stream-specific paths
        parts = path.split("/")
        if parts and parts[0] == "stream" and len(parts) >= 3:
            stream = parts[1]
            page_type = parts[2]

            # Special handling for common stream pages
            if page_type == "products":
                return f"{stream} Products"
            elif page_type == "categories":
                return f"{stream} Categories"
            elif page_type == "dashboard":
                return f"{stream} Dashboard"
            elif page_type == "location":
                return f"{stream} Locations"
            elif page_type == "system-allocation":
                return f"{stream} System Allocation"

        page_name = path.replace("-", " ").replace("_", " ")

        page_name = " ".join(word.capitalize() for word in page_name.split())

        return page_name


# Register atexit handler to flush remaining usage records on worker shutdown
atexit.register(UsageTrackingMiddleware.flush_on_shutdown)


class SessionTrackingMiddleware:
    """
    Tracks active user sessions. Debounced: only updates last_activity
    in the database once every SESSION_TRACK_DEBOUNCE seconds per session
    to avoid a DB write on every single request.
    """

    SESSION_TRACK_DEBOUNCE = 60  # seconds — update DB at most once per minute

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if request.user.is_authenticated and hasattr(request, "session"):
            session_key = request.session.session_key
            if session_key:
                # Debounce: check if we recently updated this session
                last_tracked = request.session.get("_session_last_tracked")
                now_ts = timezone.now().timestamp()
                if last_tracked and (now_ts - last_tracked) < self.SESSION_TRACK_DEBOUNCE:
                    return response  # Skip DB write — too soon

                from .models import UserSession

                x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
                if x_forwarded_for:
                    ip = x_forwarded_for.split(",")[0]
                else:
                    ip = request.META.get("REMOTE_ADDR")

                session_obj, created = UserSession.objects.get_or_create(
                    session_key=session_key,
                    defaults={
                        "user": request.user,
                        "ip_address": ip,
                        "user_agent": request.META.get("HTTP_USER_AGENT", ""),
                    },
                )

                if not created:
                    session_obj.last_activity = timezone.now()
                    session_obj.user = request.user  # Update user in case of session reuse
                    session_obj.save(update_fields=["last_activity", "user"])

                # Record the timestamp so we debounce subsequent requests
                request.session["_session_last_tracked"] = now_ts

        return response


# =============================================================================
# Inactivity Logout Middleware
# =============================================================================


class InactivityLogoutMiddleware(MiddlewareMixin):
    """
    Injects a client-side inactivity timer into every HTML response for
    authenticated users. After INACTIVITY_TIMEOUT_SECONDS of no mouse/
    keyboard/touch/scroll activity, a professional countdown modal appears.
    If the user doesn't interact within the 60-second countdown, they are
    redirected to the logout page.

    Works for ALL templates — base.html, base_minimal.html, standalone pages.

    Settings (in settings.py — optional):
        INACTIVITY_TIMEOUT_SECONDS = 60  # default: 60 seconds
    """

    # Exempt paths that should NOT have the timer
    _EXEMPT_PATHS = ("/login/", "/logout/", "/please-login/", "/maintenance/")

    _SNIPPET = """
<!-- Inactivity Logout (injected by middleware) -->
<style>
#ilt-modal{position:fixed;top:0;left:0;width:100vw;height:100vh;display:flex;align-items:center;justify-content:center;z-index:99999}
#ilt-modal .ilt-backdrop{position:absolute;inset:0;background:rgba(15,23,42,.6);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);animation:iltBdIn .4s ease}
#ilt-modal .ilt-card{position:relative;z-index:1;background:#fff;border-radius:20px;padding:2.5rem 3rem 2rem;text-align:center;box-shadow:0 25px 80px rgba(0,0,0,.22),0 0 0 1px rgba(0,0,0,.04);min-width:340px;max-width:400px;animation:iltCardIn .5s cubic-bezier(.34,1.56,.64,1)}
#ilt-modal .ilt-ring-wrap{position:relative;width:110px;height:110px;margin:0 auto 1.5rem;animation:iltRingPulse 2s ease-in-out infinite}
#ilt-modal .ilt-ring-svg{width:110px;height:110px;transform:rotate(-90deg)}
#ilt-modal .ilt-ring-bg{fill:none;stroke:#e2e8f0;stroke-width:7}
#ilt-modal .ilt-ring-fill{fill:none;stroke:#0b5fff;stroke-width:7;stroke-linecap:round;transition:stroke-dashoffset 1s linear,stroke .8s ease}
#ilt-modal .ilt-ring-glow{fill:none;stroke:#0b5fff;stroke-width:12;stroke-linecap:round;opacity:.15;filter:blur(4px);transition:stroke-dashoffset 1s linear,stroke .8s ease}
#ilt-modal .ilt-timer{position:absolute;top:50%%;left:50%%;transform:translate(-50%%,-50%%);font-size:1.85rem;font-weight:700;color:#1e293b;font-family:'Inter',system-ui,sans-serif;transition:color .8s ease,transform .2s ease}
#ilt-modal .ilt-timer.ilt-tick{animation:iltTick .35s ease}
#ilt-modal .ilt-timer.ilt-urgent{color:#dc2626}
#ilt-modal .ilt-title{font-size:1.25rem;font-weight:700;color:#1e293b;margin:0 0 .5rem;font-family:'Inter',system-ui,sans-serif;animation:iltTextIn .6s ease .15s both}
#ilt-modal .ilt-desc{font-size:.875rem;color:#64748b;margin:0 0 1.75rem;line-height:1.5;font-family:'Inter',system-ui,sans-serif;animation:iltTextIn .6s ease .25s both}
#ilt-modal .ilt-btn{display:inline-flex;align-items:center;justify-content:center;padding:.7rem 2rem;border-radius:12px;background:linear-gradient(135deg,#0b5fff 0%%,#3b82f6 100%%);color:#fff;border:none;font-size:.875rem;font-weight:600;cursor:pointer;font-family:'Inter',system-ui,sans-serif;transition:transform .2s,box-shadow .2s;box-shadow:0 4px 15px rgba(11,95,255,.3);animation:iltBtnIn .5s ease .35s both}
#ilt-modal .ilt-btn:hover{transform:translateY(-2px) scale(1.03);box-shadow:0 8px 25px rgba(11,95,255,.4)}
#ilt-modal .ilt-btn:active{transform:translateY(0) scale(.98)}
#ilt-modal.ilt-danger .ilt-ring-fill,#ilt-modal.ilt-danger .ilt-ring-glow{stroke:#dc2626}
#ilt-modal.ilt-danger .ilt-ring-wrap{animation:iltShake .5s ease-in-out infinite}
#ilt-modal.ilt-danger .ilt-btn{background:linear-gradient(135deg,#dc2626 0%%,#ef4444 100%%);box-shadow:0 4px 15px rgba(220,38,38,.3);animation:iltBtnPulse 1.5s ease-in-out infinite}
@keyframes iltBdIn{from{opacity:0}to{opacity:1}}
@keyframes iltCardIn{from{opacity:0;transform:translateY(30px) scale(.92)}to{opacity:1;transform:translateY(0) scale(1)}}
@keyframes iltRingPulse{0%%,100%%{transform:scale(1)}50%%{transform:scale(1.04)}}
@keyframes iltTick{0%%{transform:translate(-50%%,-50%%) scale(1)}40%%{transform:translate(-50%%,-50%%) scale(1.25)}100%%{transform:translate(-50%%,-50%%) scale(1)}}
@keyframes iltTextIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
@keyframes iltBtnIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
@keyframes iltShake{0%%,100%%{transform:translateX(0)}20%%{transform:translateX(-3px)}40%%{transform:translateX(3px)}60%%{transform:translateX(-2px)}80%%{transform:translateX(2px)}}
@keyframes iltBtnPulse{0%%,100%%{box-shadow:0 4px 15px rgba(220,38,38,.3)}50%%{box-shadow:0 4px 25px rgba(220,38,38,.55)}}
</style>
<script>
(function(){
  var IDLE_MS=%d,COUNTDOWN=60,LOGOUT_URL='%s';
  var _t,_ci,_modal,_cd=COUNTDOWN;
  function reset(){
    clearTimeout(_t);clearInterval(_ci);
    if(_modal){_modal.style.display='none';_modal.classList.remove('ilt-danger');}
    _cd=COUNTDOWN;
    _t=setTimeout(showCountdown,IDLE_MS);
  }
  function showCountdown(){
    if(!_modal){
      _modal=document.createElement('div');_modal.id='ilt-modal';
      _modal.innerHTML='<div class="ilt-backdrop"></div><div class="ilt-card"><div class="ilt-ring-wrap"><svg class="ilt-ring-svg" viewBox="0 0 120 120"><circle class="ilt-ring-bg" cx="60" cy="60" r="52"/><circle class="ilt-ring-glow" id="ilt-glow" cx="60" cy="60" r="52"/><circle class="ilt-ring-fill" id="ilt-ring" cx="60" cy="60" r="52"/></svg><div class="ilt-timer" id="ilt-timer">'+COUNTDOWN+'</div></div><h2 class="ilt-title">&#9203; Session Timeout</h2><p class="ilt-desc">Your session is about to expire due to inactivity.<br>You will be logged out for security.</p><button class="ilt-btn" id="ilt-stay">Stay Signed In</button></div>';
      document.body.appendChild(_modal);
      document.getElementById('ilt-stay').addEventListener('click',reset);
    } else { _modal.style.display='flex';_modal.classList.remove('ilt-danger'); }
    var ring=document.getElementById('ilt-ring'),glow=document.getElementById('ilt-glow'),C=2*Math.PI*52;
    if(ring){ring.style.strokeDasharray=C;ring.style.strokeDashoffset='0';}
    if(glow){glow.style.strokeDasharray=C;glow.style.strokeDashoffset='0';}
    var timerEl=document.getElementById('ilt-timer');
    timerEl.textContent=_cd;
    _ci=setInterval(function(){
      _cd--;
      timerEl.textContent=_cd;
      timerEl.classList.remove('ilt-tick');void timerEl.offsetWidth;timerEl.classList.add('ilt-tick');
      var off=(C*(1-_cd/COUNTDOWN)).toString();
      if(ring)ring.style.strokeDashoffset=off;
      if(glow)glow.style.strokeDashoffset=off;
      if(_cd<=10){_modal.classList.add('ilt-danger');timerEl.classList.add('ilt-urgent');}
      if(_cd<=0){clearInterval(_ci);window.location.href=LOGOUT_URL;}
    },1000);
  }
  ['mousemove','keydown','touchstart','scroll'].forEach(function(e){document.addEventListener(e,reset,true);});
  reset();
})();
</script>
"""

    def process_response(self, request, response):
        # Skip for non-HTML
        content_type = response.get("Content-Type", "")
        if "text/html" not in content_type:
            return response

        # Skip for unauthenticated users
        if not hasattr(request, "user") or not request.user.is_authenticated:
            return response

        # Skip exempt paths
        path = request.path
        if any(path.startswith(p) or path.endswith(p.lstrip("/")) for p in self._EXEMPT_PATHS):
            return response

        # Build the snippet with configurable timeout
        timeout_ms = getattr(django_settings, "INACTIVITY_TIMEOUT_SECONDS", 60) * 1000
        logout_url = "/logout/"
        try:
            from django.urls import reverse

            logout_url = reverse("logout")
        except Exception:
            pass

        snippet = self._SNIPPET % (timeout_ms, logout_url)

        # Inject before the LAST </body> (use rfind to avoid matching
        # </body> strings inside <script> blocks)
        content = response.content.decode(response.charset)
        body_idx = content.rfind("</body>")
        if body_idx != -1:
            content = content[:body_idx] + snippet + content[body_idx:]
        else:
            html_idx = content.rfind("</html>")
            if html_idx != -1:
                content = content[:html_idx] + snippet + content[html_idx:]
            else:
                return response

        response.content = content.encode(response.charset)
        response["Content-Length"] = len(response.content)
        return response


# =============================================================================
# Feature Access Control Middleware
# =============================================================================


class FeatureAccessMiddleware:
    """
    Enforce the Feature Access Control matrix.

    For every incoming request this middleware:
    1. Resolves the Django URL *name* from ``request.path_info``.
    2. Checks if that URL name belongs to a registered Feature.
    3. Looks up whether any of the user's roles have ``has_access=True``
       for that Feature.
    4. Blocks with a redirect (HTML) or JSON 403 (AJAX) when denied.

    This middleware MUST run **after** ``BusinessUnitURLMiddleware`` because
    ``request.path_info`` is already rewritten at that point.

    Notes:
    - ``app_admin`` is always exempted (no restrictions).
    - Anonymous / unauthenticated requests are skipped (handled elsewhere).
    - Static, admin, login, and API health endpoints are skipped.
    - The url-name → feature mapping is cached in memory and rebuilt
      when a Feature is saved/deleted (see ``Feature.save()``).
    """

    # ── In-memory cache ────────────────────────────────────────────────
    _url_feature_cache: dict[str, int] = {}  # {url_name: feature_id}
    _cache_lock = threading.Lock()
    _cache_built = False

    # Paths never subject to feature gating
    EXEMPT_PREFIXES = (
        "/login/",
        "/logout/",
        "/register/",
        "/please_login/",
        "/select-bu/",
        "/change-bu/",
        "/manage-business-units/",
        "/admin/",
        "/static/",
        "/media/",
        "/phnx-admin-secure/",
        "/api/health/",
        "/api/version/",
    )
    EXEMPT_EXACT = ("/", "")

    def __init__(self, get_response):
        self.get_response = get_response

    # ── Build / rebuild cache ──────────────────────────────────────────
    @classmethod
    def _build_cache(cls):
        """Build a dict mapping every registered url_name → feature.id."""
        from .models import Feature

        mapping = {}
        try:
            for feat in Feature.objects.filter(is_active=True):
                for uname in feat.url_names or []:
                    mapping[uname] = feat.id
        except Exception:
            # Table may not exist yet (pre-migration)
            pass
        with cls._cache_lock:
            cls._url_feature_cache = mapping
            cls._cache_built = True

    @classmethod
    def invalidate_cache(cls):
        """Call when Feature rows change to force a rebuild on next request."""
        with cls._cache_lock:
            cls._cache_built = False

    # ── Main entry-point ───────────────────────────────────────────────
    def __call__(self, request):
        # Build the cache on first request (or after invalidation)
        if not self.__class__._cache_built:
            self.__class__._build_cache()

        # Skip for unauthenticated users, exempt URLs, non-GET-ish requests
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return self.get_response(request)

        path = request.path_info
        if path in self.EXEMPT_EXACT or any(path.startswith(p) for p in self.EXEMPT_PREFIXES):
            return self.get_response(request)

        # App admins (explicit role) are never blocked
        try:
            cp = user.custom_profile
        except Exception:
            from .models import CustomUser

            cp, _ = CustomUser.objects.get_or_create(user=user)

        if "app_admin" in cp._roles_set:
            return self.get_response(request)

        # Resolve the URL name
        from django.urls import Resolver404, resolve

        try:
            match = resolve(path)
            url_name = match.url_name
        except Resolver404:
            return self.get_response(request)

        if not url_name:
            return self.get_response(request)

        # Look up in cache
        feature_id = self._url_feature_cache.get(url_name)
        if feature_id is None:
            # This URL isn't governed by any Feature → allow
            return self.get_response(request)

        # Check access for any of the user's roles
        user_roles = cp._roles_set
        if not user_roles:
            # User has no roles at all → deny
            return self._deny(request)

        from .models import FeatureRoleAccess

        has_access = FeatureRoleAccess.objects.filter(
            feature_id=feature_id,
            role__in=user_roles,
            has_access=True,
        ).exists()

        if has_access:
            # Mark on the user object so view-level permission helpers
            # know this request was already authorised by Feature Access Control.
            request.user._fac_granted = True
            return self.get_response(request)

        return self._deny(request)

    # ── Deny helper ────────────────────────────────────────────────────
    _DENY_MSG = (
        "Access denied — you do not have permission to use this feature. "
        "Contact your administrator if you need access."
    )

    def _deny(self, request):
        is_ajax = (
            request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest"
            or request.content_type == "application/json"
            or "application/json" in request.META.get("HTTP_ACCEPT", "")
        )
        if is_ajax:
            return JsonResponse(
                {"error": "You do not have permission to access this feature."},
                status=403,
            )
        from django.contrib import messages

        # Drain any previously queued messages so they don't pile up
        # when the user hits multiple denied pages in quick succession.
        storage = messages.get_messages(request)
        kept = []
        for m in storage:
            # Drop old FAC deny messages; keep everything else
            if str(m) != self._DENY_MSG:
                kept.append(m)
        # Re-add the kept (non-FAC) messages
        for m in kept:
            messages.add_message(request, m.level, str(m), extra_tags=m.extra_tags)

        # Add exactly one deny message
        messages.error(request, self._DENY_MSG)

        # Redirect to dashboard (BU-prefixed if applicable)
        bu_code = getattr(request, "current_bu_code", None)
        if bu_code:
            return redirect(f"/bu/{bu_code}/dashboard/")
        return redirect("dashboard")


# =============================================================================
# DevTools Protection Middleware
# =============================================================================


class DevToolsProtectionMiddleware(MiddlewareMixin):
    """
    When the SiteSetting.devtools_protection flag is ON, injects a small
    JavaScript snippet into every HTML response that blocks:
      • Right-click context menu
      • F12
      • Ctrl+Shift+I / J / C  (DevTools / Console / Element picker)
      • Ctrl+U  (View Source)

    Works for ALL templates — base.html, base_minimal.html, and standalone.
    """

    _JS_SNIPPET = """
<!-- DevTools Protection (injected by middleware) -->
<script>
(function(){
    document.addEventListener('contextmenu',function(e){e.preventDefault();return false;});
    document.addEventListener('keydown',function(e){
        if(e.key==='F12'||e.keyCode===123){e.preventDefault();return false;}
        if(e.ctrlKey&&e.shiftKey&&/^[IJCijc]$/.test(e.key)){e.preventDefault();return false;}
        if(e.ctrlKey&&!e.shiftKey&&!e.altKey&&/^[Uu]$/.test(e.key)){e.preventDefault();return false;}
    });
})();
</script>
"""

    def process_response(self, request, response):
        # Only inject into HTML responses
        content_type = response.get("Content-Type", "")
        if "text/html" not in content_type:
            return response

        # Check the toggle
        try:
            from products.models import SiteSetting

            if not SiteSetting.load().devtools_protection:
                return response
        except Exception:
            return response

        # Inject just before the LAST </body> (use rfind to avoid matching
        # </body> strings inside <script> blocks)
        content = response.content.decode(response.charset)
        body_idx = content.rfind("</body>")
        if body_idx != -1:
            content = content[:body_idx] + self._JS_SNIPPET + content[body_idx:]
        else:
            html_idx = content.rfind("</html>")
            if html_idx != -1:
                content = content[:html_idx] + self._JS_SNIPPET + content[html_idx:]
            else:
                return response

        response.content = content.encode(response.charset)
        response["Content-Length"] = len(response.content)
        return response
