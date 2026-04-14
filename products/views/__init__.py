"""Products app views package.

Split from monolithic views.py for maintainability.
All view functions are re-exported here for backward compatibility.
"""

# Re-export everything from submodules  # noqa: F401,F403
# pylint: disable=unused-wildcard-import,wildcard-import
from ._helpers import *
from .activity_data import *
from .admin_features import *
from .ai_features import *
from .allocation import *
from .allocation_ops import *
from .auth import *
from .booking import *
from .booking_history_api import *
from .build_servers import *
from .calibration_compliance import *
from .chat_groups import *
from .chat_support import *
from .communication import *
from .compliance_regulatory import *
from .dashboard import *
from .dashboard_main import *
from .feature_access import *
from .floors_os import *
from .holistic_data import *
from .holistic_infra import *
from .holistic_projects import *
from .infra_downtime import *
from .inventory_alerts import *
from .legacy import *
from .lifecycle_inventory import *
from .monitoring import *
from .notes import *
from .notifications_metrics import *
from .product_bulk import *
from .product_history_categories import *
from .products import *
from .projects import *
from .recurring import *
from .regulatory import *
from .reservation_actions import *
from .resource_management import *
from .resource_weekly import *
from .settings_features import *
from .streams import *
from .sublevels_qr import *
from .support_tickets import *
from .system_crud import *
from .system_tags import *
from .systems_api import *
from .tld import *
from .tld_badge_tools import *
from .usage_tracking import *
from .user_data import *
from .user_management import *
from .vendor import *
from .waitlist import *
from .waste import *
from .waste_schedules import *
from .approval_workflows import *
from .search import *
from .shift_handover import *
from .demo_requests import *
