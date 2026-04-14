# pylint: disable=too-many-lines
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect
from django.urls import path

from . import views  # pylint: disable=no-name-in-module
from .views import (
    CustomPasswordChangeDoneView,
    binaries_system_types_api,
    custom_password_change,
    delete_legacy_excel,
    delete_sub_level,
    delete_zenition_product_api,
    execute_robocopy,
    fetch_zenition_excels,
    merge_excels,
    os_system_types_api,
    preview_legacy_excel,
    preview_zenition_excel,
    product_entries_api,
    stream_deletion_history,
    sub_level_list,
    system_types_category_mapping_api,
    test_repo_view,
)

urlpatterns = [
    path("", views.home, name="home"),
    # Business Unit selection (must be before any stream-specific URLs)
    path("select-bu/", views.select_bu, name="select_bu"),
    path("change-bu/", views.change_bu, name="change_bu"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("login/", views.user_login, name="login"),
    path("register/", views.user_register, name="register"),
    path("check-availability/", views.check_availability, name="check_availability"),
    path("logout/", views.user_logout, name="logout"),
    path("users/", views.user_list, name="user_list"),
    path("users/change-role/<int:user_id>/", views.change_user_role, name="change_user_role"),
    path("users/promote/<int:user_id>/", views.promote_user, name="promote_user"),
    path("users/remove/<int:user_id>/", views.remove_user, name="remove_user"),
    path("users/deactivate/<int:user_id>/", views.deactivate_user, name="deactivate_user"),
    path("users/reactivate/<int:user_id>/", views.reactivate_user, name="reactivate_user"),
    path("users/depromote/<int:user_id>/", views.depromote_user, name="depromote_user"),
    path("users/approve/<int:user_id>/", views.approve_user, name="approve_user"),
    path("users/decline/<int:user_id>/", views.decline_user, name="decline_user"),
    # Role and stream management URLs
    path("users/<int:user_id>/assign-role/", views.assign_role, name="assign_role"),
    path("users/<int:user_id>/remove-role/", views.remove_role, name="remove_role"),
    path("users/<int:user_id>/grant-stream/", views.grant_stream_access, name="grant_stream_access"),
    path("users/<int:user_id>/revoke-stream/", views.revoke_stream_access, name="revoke_stream_access"),
    path("manage-streams/", views.manage_streams, name="manage_streams"),
    path("manage-streams/export-csv/", views.export_streams_csv, name="export_streams_csv"),
    path("manage-streams/clone/", views.clone_stream, name="clone_stream"),
    path("manage-business-units/", views.manage_business_units, name="manage_business_units"),
    path("manage-business-units/deletion/<int:pk>/review/", views.bu_deletion_review, name="bu_deletion_review"),
    path("manage-business-units/deletion/<int:pk>/cancel/", views.bu_deletion_cancel, name="bu_deletion_cancel"),
    path("users/download/excel/", views.download_users_excel, name="download_users_excel"),
    path("users/download/pdf/", views.download_users_pdf, name="download_users_pdf"),
    path("users/upload/excel/", views.upload_products_excel, name="upload_products_excel"),
    path("users/add-participant/", views.add_participant, name="add_participant"),
    path("users/remove-participant/<int:participant_id>/", views.remove_participant, name="remove_participant"),
    path(
        "users/download/excel-with-os-binaries/",
        views.download_inventory_with_os_binaries_excel,
        name="download_inventory_with_os_binaries_excel",
    ),
    path("users/profile/", views.user_profile, name="user_profile"),
    path("users/profile/<int:user_id>/", views.user_profile, name="user_profile_other"),
    path("stream/<str:stream>/dashboard/", views.dashboard, name="dashboard_stream"),
    path("stream/<str:stream>/categories/", views.category_list, name="category_list_stream"),
    path("stream/<str:stream>/categories/add/", views.category_create, name="category_create_stream"),
    path("stream/<str:stream>/categories/<int:pk>/edit/", views.category_edit, name="category_edit_stream"),
    path("stream/<str:stream>/categories/<int:pk>/delete/", views.category_delete, name="category_delete_stream"),
    path("stream/<str:stream>/categories/bulk-delete/", views.category_bulk_delete, name="category_bulk_delete_stream"),
    path("stream/<str:stream>/categories/export-csv/", views.category_export_csv, name="category_export_csv_stream"),
    path("stream/<str:stream>/products/", views.product_list, name="product_list_stream"),
    path("stream/<str:stream>/products/add/", views.product_create, name="product_create_stream"),
    path("stream/<str:stream>/products/bulk-delete/", views.product_bulk_delete, name="product_bulk_delete_stream"),
    path("stream/<str:stream>/products/bulk-status/", views.product_bulk_status, name="product_bulk_status_stream"),
    path("stream/<str:stream>/products/bulk-export/", views.product_bulk_export, name="product_bulk_export_stream"),
    path("stream/<str:stream>/products/<int:pk>/", views.product_detail, name="product_detail_stream"),
    path("stream/<str:stream>/products/<int:pk>/edit/", views.product_edit, name="product_edit_stream"),
    path("stream/<str:stream>/products/<int:pk>/delete/", views.product_delete, name="product_delete_stream"),
    path(
        "stream/<str:stream>/products/<int:pk>/history/", views.product_history_ajax, name="product_history_ajax_stream"
    ),
    path(
        "stream/<str:stream>/products/<int:pk>/download_qr/",
        views.download_qr_with_details,
        name="download_qr_with_details_stream",
    ),
    path("stream/<str:stream>/system-allocation/", views.system_allocation, name="system_allocation_stream"),
    path("stream/<str:stream>/system-allocation/allocate/", views.allocate_system, name="allocate_system_stream"),
    path(
        "stream/<str:stream>/system-allocation/blocked/", views.get_blocked_systems, name="get_blocked_systems_stream"
    ),
    path("stream/<str:stream>/system-allocation/release/", views.release_system, name="release_system_stream"),
    path(
        "stream/<str:stream>/system-allocation/cancel-day/", views.cancel_booking_day, name="cancel_booking_day_stream"
    ),
    path(
        "stream/<str:stream>/system-allocation/cancel-days/",
        views.cancel_booking_days,
        name="cancel_booking_days_stream",
    ),
    path("stream/<str:stream>/system-allocation/extend/", views.extend_system, name="extend_system_stream"),
    path("stream/<str:stream>/system-allocation/opt-change/", views.opt_change_system, name="opt_change_system_stream"),
    path("stream/<str:stream>/system-allocation/add-system/", views.add_system, name="add_system_stream"),
    path("stream/<str:stream>/system-allocation/metrics/", views.get_system_metrics, name="get_system_metrics"),
    path("stream/<str:stream>/system-allocation/delete-system/", views.delete_system, name="delete_system_stream"),
    path("stream/<str:stream>/system-allocation/update-system/", views.update_system, name="update_system_stream"),
    path(
        "stream/<str:stream>/system-allocation/reset-utilization/",
        views.reset_system_utilization,
        name="reset_system_utilization_stream",
    ),
    path("stream/<str:stream>/system-allocation/status/", views.system_status_api, name="system_status_api_stream"),
    path("stream/<str:stream>/system-allocation/metrics/", views.system_metrics_api, name="system_metrics_api_stream"),
    path(
        "stream/<str:stream>/system-allocation/details/<int:system_id>/",
        views.system_details_api,
        name="system_details_api_stream",
    ),
    path("stream/<str:stream>/system-allocation/nc-details/", views.get_nc_details, name="get_nc_details"),
    path("stream/<str:stream>/system-allocation/nc-details/save/", views.save_nc_details, name="save_nc_details"),
    path("stream/<str:stream>/system-allocation/nc-details/all/", views.get_all_nc_details, name="get_all_nc_details"),
    path(
        "stream/<str:stream>/system-allocation/historical-status/",
        views.get_historical_system_status,
        name="get_historical_system_status",
    ),
    # Downtime tracking URLs
    path("stream/<str:stream>/downtime/", views.downtime_dashboard, name="downtime_dashboard"),
    path("stream/<str:stream>/downtime/events/", views.system_downtime_events, name="system_downtime_events"),
    path(
        "stream/<str:stream>/downtime/events/<int:system_id>/",
        views.system_downtime_events,
        name="system_downtime_events_for_system",
    ),
    path(
        "stream/<str:stream>/downtime/event/<int:downtime_id>/",
        views.system_downtime_event_detail,
        name="system_downtime_event_detail",
    ),
    path("stream/<str:stream>/downtime/resolve/<int:downtime_id>/", views.resolve_downtime, name="resolve_downtime"),
    path("stream/<str:stream>/downtime/metrics/", views.system_downtime_metrics, name="system_downtime_metrics"),
    path(
        "stream/<str:stream>/downtime/metrics/<int:system_id>/",
        views.system_downtime_metrics,
        name="system_downtime_metrics_for_system",
    ),
    # Server-side Ticket Tracking API
    path("stream/<str:stream>/tickets/", views.system_tickets_api, name="system_tickets_api"),
    path(
        "stream/<str:stream>/tickets/<int:ticket_id>/action/", views.system_ticket_action, name="system_ticket_action"
    ),
    # User Booking History & Conflict Checking API
    path("stream/<str:stream>/booking/history/", views.user_booking_history_api, name="user_booking_history_api"),
    path("stream/<str:stream>/booking/conflicts/", views.booking_conflicts_api, name="booking_conflicts_api"),
    # Gantt / Timeline Data API
    path("stream/<str:stream>/system-allocation/gantt/", views.gantt_data_api, name="gantt_data_api"),
    path("stream/<str:stream>/location/", views.location_list, name="location_list_stream"),
    path("stream/<str:stream>/location/add/", views.location_create, name="location_create_stream"),
    path("stream/<str:stream>/location/<int:pk>/edit/", views.location_edit, name="location_edit_stream"),
    path("stream/<str:stream>/location/<int:pk>/delete/", views.location_delete, name="location_delete_stream"),
    # Allocation Tree URLs
    path("stream/<str:stream>/allocation-tree/", views.allocation_tree, name="allocation_tree_stream"),
    path("stream/<str:stream>/allocation-tree/create-tag/", views.create_system_tag, name="create_system_tag_stream"),
    path(
        "stream/<str:stream>/allocation-tree/delete-tag/<int:tag_id>/",
        views.delete_system_tag,
        name="delete_system_tag_stream",
    ),
    path(
        "stream/<str:stream>/allocation-tree/manage-items/<int:tag_id>/",
        views.manage_tag_items,
        name="manage_tag_items_stream",
    ),
    path(
        "stream/<str:stream>/allocation-tree/get-items/", views.get_available_items, name="get_available_items_stream"
    ),
    path(
        "stream/<str:stream>/allocation-tree/history/<int:system_id>/",
        views.get_system_tag_history,
        name="get_system_tag_history_stream",
    ),
    path("stream/delete/", views.delete_stream, name="delete_stream"),
    path(
        "stream/<str:stream>/system/<int:system_id>/status-history/",
        views.system_status_history,
        name="system_status_history",
    ),
    path("users/restore-backup/<int:backup_id>/", views.restore_user_backup, name="restore_user_backup"),
    path("users/delete-backup/<int:backup_id>/", views.delete_user_backup, name="delete_user_backup"),
    path("analytics_dashboard/", views.analytics_dashboard, name="analytics_dashboard"),
    path("stream-deletion-history/", stream_deletion_history, name="stream_deletion_history"),
    path("build_os_info/", views.build_os_info, name="build_os_info"),
    path("api/product-entries/", product_entries_api, name="product_entries_api"),
    path("api/add-zenition-product/", views.add_zenition_product_api, name="add_zenition_product_api"),
    path("api/delete-zenition-product/", delete_zenition_product_api, name="delete_zenition_product_api"),
    path("api/os-system-types/", os_system_types_api, name="os_system_types_api"),
    path("api/binaries-system-types/", binaries_system_types_api, name="binaries_system_types_api"),
    path(
        "api/system-types-category-mapping/",
        system_types_category_mapping_api,
        name="system_types_category_mapping_api",
    ),
    path("api/communication/", views.communication_api, name="communication_api"),
    path("api/communication/upload/", views.upload_communication_attachment, name="upload_communication_attachment"),
    path(
        "api/communication/attachment/<int:attachment_id>/",
        views.serve_communication_attachment,
        name="serve_communication_attachment",
    ),
    path("api/execute-robocopy/", execute_robocopy, name="execute_robocopy"),
    path("faq/", views.faq, name="faq"),
    path("stream/<str:stream>/faq/", views.faq, name="faq_stream"),
    # Support Tickets
    path("support/", views.support_ticket_list, name="support_ticket_list"),
    path("support/create/", views.support_ticket_create, name="support_ticket_create"),
    path("support/<int:ticket_id>/", views.support_ticket_detail, name="support_ticket_detail"),
    # Live Support Chat
    path("live-support/start/", views.live_support_start, name="live_support_start"),
    path("live-support/<int:session_id>/messages/", views.live_support_messages, name="live_support_messages"),
    path("live-support/<int:session_id>/close/", views.live_support_close, name="live_support_close"),
    path("live-support/admin-queue/", views.live_support_admin_queue, name="live_support_admin_queue"),
    path("live-support/admin/", views.live_support_admin_page, name="live_support_admin_page"),
    path("password_change/", custom_password_change, name="password_change"),
    path("password_change/done/", CustomPasswordChangeDoneView.as_view(), name="password_change_done"),
    path("stream/<str:stream>/subleveldata/", sub_level_list, name="sub_level_list_stream"),
    path("stream/<str:stream>/subleveldata/delete/<int:sublevel_id>/", delete_sub_level, name="delete_sub_level"),
    path("stream/<str:stream>/sublevels/bulk-delete/", views.bulk_delete_sublevels, name="bulk_delete_sublevels"),
    path("stream/<str:stream>/sublevels/bulk-update/", views.bulk_update_sublevels, name="bulk_update_sublevels"),
    path("stream/<str:stream>/sublevels/export/", views.export_sublevels, name="export_sublevels"),
    path("stream/<str:stream>/subleveltools/", views.sub_level_tool_list, name="sub_level_tool_list_stream"),
    path(
        "stream/<str:stream>/subleveltools/delete/<int:subleveltool_id>/",
        views.delete_sub_level_tool,
        name="delete_sub_level_tool",
    ),
    path(
        "stream/<str:stream>/subleveltools/bulk-delete/",
        views.bulk_delete_subleveltools,
        name="bulk_delete_subleveltools",
    ),
    path(
        "stream/<str:stream>/subleveltools/bulk-update/",
        views.bulk_update_subleveltools,
        name="bulk_update_subleveltools",
    ),
    path("stream/<str:stream>/subleveltools/export/", views.export_subleveltools, name="export_subleveltools"),
    path("notifications/mark_read/", views.mark_notifications_read, name="mark_notifications_read"),
    path("notifications/<int:pk>/toggle_read/", views.toggle_notification_read, name="toggle_notification_read"),
    path("test-repo/", test_repo_view, name="test_repo"),
    path("preview-legacy-excel/<int:upload_id>/", preview_legacy_excel, name="preview_legacy_excel"),
    path("preview-zenition-excel/<int:upload_id>/", preview_zenition_excel, name="preview_zenition_excel"),
    path("merge-excels/", merge_excels, name="merge_excels"),
    path("fetch-legacy-excels/", views.fetch_legacy_excels, name="fetch_legacy_excels"),
    path("delete-legacy-excel/<int:upload_id>/", delete_legacy_excel, name="delete_legacy_excel"),
    path(
        "preview-legacy-excel-by-filename/<str:filename>/",
        views.preview_legacy_excel_by_filename,
        name="preview_legacy_excel_by_filename",
    ),
    path("save-test-environment/", views.save_test_environment, name="save_test_environment"),
    path("export-data/", views.export_data, name="export_data"),
    path("fetch-zenition-excels/", fetch_zenition_excels, name="fetch_zenition_excels"),
    path("personal_trackboard/", views.personal_trackboard, name="personal_trackboard"),
    path("usage-tracking/", views.usage_tracking, name="usage_tracking"),
    path("usage-tracking-data/", views.usage_tracking_data, name="usage_tracking_data"),
    # API endpoints for dashboard
    path("api/dashboard/data/", views.dashboard_api_data, name="dashboard_api_data"),
    path("api/dashboard/activity/", views.update_user_activity, name="update_user_activity"),
    # Onboarding / Guided Tour API
    path("api/onboarding/status/", views.onboarding_status_api, name="onboarding_status_api"),
    path("api/onboarding/complete/", views.onboarding_complete_api, name="onboarding_complete_api"),
    path("api/onboarding/reset/", views.onboarding_reset_api, name="onboarding_reset_api"),
    path("system/metrics/<int:system_id>/", views.system_metrics, name="system_metrics"),
    path("system/metrics/update/<int:system_id>/", views.update_system_metrics, name="update_system_metrics"),
    path("stream/<str:stream>/export-systems-log/", views.export_systems_log, name="export_systems_log"),
    path("notes/", views.notes_list, name="notes_list"),
    path("notes/<int:pk>/", views.note_detail, name="note_detail"),
    path("notes/create/", views.note_create, name="note_create"),
    path("notes/<int:pk>/edit/", views.note_edit, name="note_edit"),
    path("notes/<int:pk>/delete/", views.note_delete, name="note_delete"),
    path("notes/<int:pk>/share/", views.share_note, name="share_note"),
    path("notes/shared/", views.shared_notes, name="shared_notes"),
    path("notes/shared-by-me/", views.shared_by_me, name="shared_by_me"),
    path("shared-notes/<int:pk>/remove/", views.remove_shared_note, name="remove_shared_note"),
    path("notes/api/tags/", views.note_tags_api, name="note_tags_api"),
    path("notes/api/tags/create/", views.note_tag_create_api, name="note_tag_create_api"),
    path("notes/api/tags/<int:pk>/delete/", views.note_tag_delete_api, name="note_tag_delete_api"),
    path("notes/api/tags/<int:pk>/update/", views.note_tag_update_api, name="note_tag_update_api"),
    # Project Status URLs
    path("projects/", views.project_status, name="project_status"),
    path("projects/delete/", views.delete_project, name="delete_project"),
    path("projects/milestones/", views.project_milestone_api, name="project_milestone_api"),
    path("projects/attachments/", views.project_attachment_api, name="project_attachment_api"),
    path("projects/dependencies/", views.project_dependency_api, name="project_dependency_api"),
    # Resource Allocation (FTE Tracking) APIs
    path("projects/resource-allocation/", views.resource_allocation_api, name="resource_allocation_api"),
    path("projects/resource-person/", views.resource_person_api, name="resource_person_api"),
    path("projects/resource-allocation/export/", views.resource_allocation_export, name="resource_allocation_export"),
    path("projects/resource-allocation/config/", views.resource_allocation_config, name="resource_allocation_config"),
    path("projects/resource-allocation/component/", views.resource_component_api, name="resource_component_api"),
    path("projects/resource-person/assign/", views.resource_person_assign_api, name="resource_person_assign_api"),
    path("projects/resource-allocation/year/", views.resource_year_api, name="resource_year_api"),
    path(
        "projects/resource-allocation/weekly/",
        views.resource_weekly_allocation_api,
        name="resource_weekly_allocation_api",
    ),
    path(
        "projects/resource-allocation/lookup/<str:lookup_type>/", views.resource_lookup_api, name="resource_lookup_api"
    ),
    path("projects/resource-allocation/notes/", views.resource_cell_note_api, name="resource_cell_note_api"),
    path(
        "projects/resource-allocation/locks/", views.resource_allocation_lock_api, name="resource_allocation_lock_api"
    ),
    path(
        "projects/resource-allocation/compare/",
        views.resource_allocation_compare_api,
        name="resource_allocation_compare_api",
    ),
    path(
        "projects/resource-allocation/import/",
        views.resource_allocation_import_api,
        name="resource_allocation_import_api",
    ),
    path(
        "projects/resource-allocation/heatmap/",
        views.resource_allocation_heatmap_api,
        name="resource_allocation_heatmap_api",
    ),
    # Holistic Dashboard URLs (independent, no stream)
    path("holistic-dashboard/", views.holistic_dashboard, name="holistic_dashboard"),
    path("holistic-dashboard/create/", views.holistic_system_create, name="holistic_system_create"),
    path("holistic-dashboard/<int:pk>/", views.holistic_system_detail, name="holistic_system_detail"),
    path("holistic-dashboard/<int:pk>/edit/", views.holistic_system_edit, name="holistic_system_edit"),
    path("holistic-dashboard/<int:pk>/delete/", views.holistic_system_delete, name="holistic_system_delete"),
    path(
        "holistic-dashboard/weekly-data/update/", views.holistic_weekly_data_update, name="holistic_weekly_data_update"
    ),
    path("holistic-dashboard/export/excel/", views.holistic_export_excel, name="holistic_export_excel"),
    path("holistic-dashboard/export/pdf/", views.holistic_export_pdf, name="holistic_export_pdf"),
    path("holistic-dashboard/bulk-update/", views.holistic_bulk_update, name="holistic_bulk_update"),
    path(
        "holistic-dashboard/assign-project-to-week/",
        views.holistic_assign_project_to_week,
        name="holistic_assign_project_to_week",
    ),
    path(
        "holistic-dashboard/get-project-assignments/",
        views.holistic_get_project_assignments,
        name="holistic_get_project_assignments",
    ),
    path("holistic-dashboard/get-week-data/", views.holistic_get_week_data, name="holistic_get_week_data"),
    path("holistic-dashboard/all-systems-list/", views.holistic_all_systems_list, name="holistic_all_systems_list"),
    path("holistic-dashboard/graph-data/<int:system_id>/", views.holistic_graph_data, name="holistic_graph_data"),
    path(
        "holistic-dashboard/export-graph-data/<int:system_id>/",
        views.holistic_export_graph_data,
        name="holistic_export_graph_data",
    ),
    # Build Servers URLs
    path("build-servers/", views.build_servers_dashboard, name="build_servers_dashboard"),
    path("build_servers_dashboard/", views.build_servers_dashboard, name="build_servers_dashboard_underscore"),
    path("stream/<str:stream>/build-servers/", views.build_servers_list, name="build_servers_list"),
    path("stream/<str:stream>/build-servers/create/", views.build_server_create, name="build_server_create"),
    path("stream/<str:stream>/build-servers/<int:server_id>/", views.build_server_detail, name="build_server_detail"),
    path("stream/<str:stream>/build-servers/<int:server_id>/edit/", views.build_server_edit, name="build_server_edit"),
    path(
        "stream/<str:stream>/build-servers/<int:server_id>/delete/",
        views.build_server_delete,
        name="build_server_delete",
    ),
    path("stream/<str:stream>/build-servers/api/", views.build_servers_api, name="build_servers_api"),
    path("stream/<str:stream>/build-servers/export/", views.build_servers_export, name="build_servers_export"),
    # Floor Management URLs (Stream-specific)
    path("stream/<str:stream>/floors/", views.floor_list, name="floor_list"),
    path("stream/<str:stream>/floors/create/", views.floor_create, name="floor_create"),
    path("stream/<str:stream>/floors/<int:floor_id>/edit/", views.floor_edit, name="floor_edit"),
    path("stream/<str:stream>/floors/<int:floor_id>/delete/", views.floor_delete, name="floor_delete"),
    path("stream/<str:stream>/operating-systems/", views.operating_system_list, name="operating_system_list"),
    path(
        "stream/<str:stream>/operating-systems/create/", views.operating_system_create, name="operating_system_create"
    ),
    path(
        "stream/<str:stream>/operating-systems/<int:os_id>/edit/",
        views.operating_system_edit,
        name="operating_system_edit",
    ),
    path(
        "stream/<str:stream>/operating-systems/<int:os_id>/delete/",
        views.operating_system_delete,
        name="operating_system_delete",
    ),
    # =============================================================================
    # HUB PAGES (Stream Selection)
    # =============================================================================
    path("reservations/", views.reservations_hub, name="reservations_hub"),
    path("calibration/", views.calibration_hub, name="calibration_hub"),
    path("compliance/", views.compliance_hub, name="compliance_hub"),
    # =============================================================================
    # RECURRING RESERVATIONS & WAITLIST MANAGEMENT URLs
    # =============================================================================
    # Unified Booking Hub
    path("stream/<str:stream>/booking/", views.unified_booking_hub, name="unified_booking_hub"),
    path("stream/<str:stream>/booking/quick-book/", views.quick_book_system, name="quick_book_system"),
    path(
        "stream/<str:stream>/booking/check-availability/",
        views.check_system_availability,
        name="check_system_availability",
    ),
    path("stream/<str:stream>/booking/my-bookings/", views.my_bookings, name="my_bookings"),
    # Recurring Reservations
    path(
        "stream/<str:stream>/recurring-reservations/",
        views.recurring_reservations_list,
        name="recurring_reservations_list",
    ),
    path(
        "stream/<str:stream>/recurring-reservations/create/",
        views.recurring_reservation_create,
        name="recurring_reservation_create",
    ),
    path(
        "stream/<str:stream>/recurring-reservations/check-conflicts/",
        views.check_recurring_conflicts,
        name="check_recurring_conflicts",
    ),
    path(
        "stream/<str:stream>/recurring-reservations/<int:pk>/",
        views.recurring_reservation_detail,
        name="recurring_reservation_detail",
    ),
    path(
        "stream/<str:stream>/recurring-reservations/<int:pk>/edit/",
        views.recurring_reservation_edit,
        name="recurring_reservation_edit",
    ),
    path(
        "stream/<str:stream>/recurring-reservations/<int:pk>/delete/",
        views.recurring_reservation_delete,
        name="recurring_reservation_delete",
    ),
    path(
        "stream/<str:stream>/recurring-reservations/<int:pk>/toggle-status/",
        views.recurring_reservation_toggle_status,
        name="recurring_reservation_toggle_status",
    ),
    # Reservation Instance Management
    path(
        "stream/<str:stream>/reservation-instances/<int:pk>/confirm/",
        views.reservation_instance_confirm,
        name="reservation_instance_confirm",
    ),
    path(
        "stream/<str:stream>/reservation-instances/<int:pk>/cancel/",
        views.reservation_instance_cancel,
        name="reservation_instance_cancel",
    ),
    # Waitlist Management
    path("stream/<str:stream>/waitlist/", views.waitlist_dashboard, name="waitlist_dashboard"),
    path("stream/<str:stream>/waitlist/join/", views.waitlist_join, name="waitlist_join"),
    path("stream/<str:stream>/waitlist/<int:pk>/", views.waitlist_entry_detail, name="waitlist_entry_detail"),
    path("stream/<str:stream>/waitlist/<int:pk>/cancel/", views.waitlist_cancel, name="waitlist_cancel"),
    path("stream/<str:stream>/waitlist/<int:pk>/fulfill/", views.waitlist_fulfill, name="waitlist_fulfill"),
    # Utilization Dashboard
    path("stream/<str:stream>/utilization/", views.utilization_dashboard, name="utilization_dashboard"),
    # Conflict Resolution
    path("stream/<str:stream>/conflicts/", views.conflicts_list, name="conflicts_list"),
    path("stream/<str:stream>/conflicts/<int:pk>/resolve/", views.conflict_resolve, name="conflict_resolve"),
    # =============================================================================
    # CALIBRATION & COMPLIANCE TRACKING URLs
    # =============================================================================
    # Calibration Dashboard and Schedules
    path("stream/<str:stream>/calibration/", views.calibration_dashboard, name="calibration_dashboard"),
    path(
        "stream/<str:stream>/calibration/schedules/", views.calibration_schedule_list, name="calibration_schedule_list"
    ),
    path(
        "stream/<str:stream>/calibration/schedules/create/",
        views.calibration_schedule_create,
        name="calibration_schedule_create",
    ),
    path(
        "stream/<str:stream>/calibration/schedules/<int:pk>/",
        views.calibration_schedule_detail,
        name="calibration_schedule_detail",
    ),
    path(
        "stream/<str:stream>/calibration/schedules/<int:pk>/edit/",
        views.calibration_schedule_edit,
        name="calibration_schedule_edit",
    ),
    path(
        "stream/<str:stream>/calibration/schedules/<int:pk>/delete/",
        views.calibration_schedule_delete,
        name="calibration_schedule_delete",
    ),
    path(
        "stream/<str:stream>/calibration/schedules/<int:pk>/complete/",
        views.calibration_record_complete,
        name="calibration_record_complete",
    ),
    path(
        "stream/<str:stream>/calibration/schedules/<int:schedule_id>/record/",
        views.calibration_record_create,
        name="calibration_record_create",
    ),
    path("stream/<str:stream>/calibration/records/", views.calibration_records_list, name="calibration_records_list"),
    # Compliance Dashboard and Documents
    path("stream/<str:stream>/compliance/", views.compliance_dashboard, name="compliance_dashboard"),
    path("stream/<str:stream>/compliance/export/", views.compliance_export_report, name="compliance_export_report"),
    path(
        "stream/<str:stream>/compliance/documents/", views.compliance_documents_list, name="compliance_documents_list"
    ),
    path(
        "stream/<str:stream>/compliance/documents/create/",
        views.compliance_document_create,
        name="compliance_document_create",
    ),
    path(
        "stream/<str:stream>/compliance/documents/<int:pk>/",
        views.compliance_document_detail,
        name="compliance_document_detail",
    ),
    path(
        "stream/<str:stream>/compliance/documents/<int:pk>/edit/",
        views.compliance_document_edit,
        name="compliance_document_edit",
    ),
    path(
        "stream/<str:stream>/compliance/documents/<int:pk>/delete/",
        views.compliance_document_delete,
        name="compliance_document_delete",
    ),
    # Regulatory Requirements
    path(
        "stream/<str:stream>/compliance/requirements/",
        views.regulatory_requirements_list,
        name="regulatory_requirements_list",
    ),
    path(
        "stream/<str:stream>/compliance/requirements/create/",
        views.regulatory_requirement_create,
        name="regulatory_requirement_create",
    ),
    path(
        "stream/<str:stream>/compliance/requirements/<int:pk>/",
        views.regulatory_requirement_detail,
        name="regulatory_requirement_detail",
    ),
    path(
        "stream/<str:stream>/compliance/requirements/<int:pk>/edit/",
        views.regulatory_requirement_edit,
        name="regulatory_requirement_edit",
    ),
    path(
        "stream/<str:stream>/compliance/requirements/<int:pk>/delete/",
        views.regulatory_requirement_delete,
        name="regulatory_requirement_delete",
    ),
    # Regulatory Checklists
    path(
        "stream/<str:stream>/compliance/checklists/",
        views.regulatory_checklists_list,
        name="regulatory_checklists_list",
    ),
    path(
        "stream/<str:stream>/compliance/checklists/create/",
        views.regulatory_checklist_create,
        name="regulatory_checklist_create",
    ),
    path(
        "stream/<str:stream>/compliance/checklists/<int:pk>/",
        views.regulatory_checklist_detail,
        name="regulatory_checklist_detail",
    ),
    path(
        "stream/<str:stream>/compliance/checklists/<int:pk>/edit/",
        views.regulatory_checklist_edit,
        name="regulatory_checklist_edit",
    ),
    path(
        "stream/<str:stream>/compliance/checklists/<int:pk>/delete/",
        views.regulatory_checklist_delete,
        name="regulatory_checklist_delete",
    ),
    path(
        "stream/<str:stream>/compliance/checklists/<int:pk>/verify/",
        views.regulatory_checklist_verify,
        name="regulatory_checklist_verify",
    ),
    # Compliance Alerts
    path("stream/<str:stream>/compliance/alerts/", views.compliance_alerts_list, name="compliance_alerts_list"),
    path(
        "stream/<str:stream>/compliance/alerts/create/", views.compliance_alert_create, name="compliance_alert_create"
    ),
    path(
        "stream/<str:stream>/compliance/alerts/<int:pk>/", views.compliance_alert_detail, name="compliance_alert_detail"
    ),
    path(
        "stream/<str:stream>/compliance/alerts/<int:pk>/edit/",
        views.compliance_alert_edit,
        name="compliance_alert_edit",
    ),
    path(
        "stream/<str:stream>/compliance/alerts/<int:pk>/delete/",
        views.compliance_alert_delete,
        name="compliance_alert_delete",
    ),
    path(
        "stream/<str:stream>/compliance/alerts/<int:pk>/acknowledge/",
        views.compliance_alert_acknowledge,
        name="compliance_alert_acknowledge",
    ),
    path(
        "stream/<str:stream>/compliance/alerts/<int:pk>/resolve/",
        views.compliance_alert_resolve,
        name="compliance_alert_resolve",
    ),
    # API Endpoints
    path(
        "stream/<str:stream>/api/waitlist-position/<int:system_id>/<str:date>/",
        views.api_get_waitlist_position,
        name="api_get_waitlist_position",
    ),
    path("stream/<str:stream>/api/check-slot/", views.api_check_slot_availability, name="api_check_slot_availability"),
    path("stream/<str:stream>/api/calibration-stats/", views.api_calibration_stats, name="api_calibration_stats"),
    # =========================================================================
    # FEATURE HUB — Dedicated hub page for advanced features
    # =========================================================================
    path("feature-hub/", views.feature_hub, name="feature_hub"),
    # =========================================================================
    # FEATURE 1: GLOBAL AUDIT LOG / ACTIVITY TIMELINE
    # =========================================================================
    path("audit-log/", views.audit_log_list, name="audit_log_list"),
    path("audit-log/export/", views.audit_log_export, name="audit_log_export"),
    path("audit-log/clear/", views.audit_log_clear, name="audit_log_clear"),
    path("audit-log/settings/", views.audit_log_settings, name="audit_log_settings"),
    path("api/audit-log/data/", views.audit_log_api_data, name="audit_log_api_data"),
    # =========================================================================
    # FEATURE 2: DASHBOARD WIDGETS / CUSTOMIZABLE HOME
    # =========================================================================
    path("api/dashboard/widgets/", views.dashboard_widgets_api, name="dashboard_widgets_api"),
    path("api/dashboard/widgets/save-layout/", views.dashboard_save_layout, name="dashboard_save_layout"),
    path("api/dashboard/widgets/reset/", views.dashboard_reset_widgets, name="dashboard_reset_widgets"),
    path("api/dashboard/widgets/<str:widget_type>/data/", views.dashboard_widget_data, name="dashboard_widget_data"),
    # =========================================================================
    # FEATURE 3: ASSET LIFECYCLE MANAGEMENT
    # =========================================================================
    path("stream/<str:stream>/lifecycle/", views.asset_lifecycle_list, name="asset_lifecycle_list"),
    path(
        "stream/<str:stream>/lifecycle/bulk-enroll/",
        views.asset_lifecycle_bulk_enroll,
        name="asset_lifecycle_bulk_enroll",
    ),
    path(
        "stream/<str:stream>/lifecycle/create/<int:product_id>/",
        views.asset_lifecycle_create,
        name="asset_lifecycle_create",
    ),
    path("stream/<str:stream>/lifecycle/<int:pk>/", views.asset_lifecycle_detail, name="asset_lifecycle_detail"),
    path("stream/<str:stream>/lifecycle/<int:pk>/edit/", views.asset_lifecycle_edit, name="asset_lifecycle_edit"),
    path(
        "stream/<str:stream>/lifecycle/<int:pk>/transition/",
        views.asset_lifecycle_transition,
        name="asset_lifecycle_transition",
    ),
    path("stream/<str:stream>/lifecycle/dashboard/", views.asset_lifecycle_dashboard, name="asset_lifecycle_dashboard"),
    # =========================================================================
    # FEATURE 4: INVENTORY ALERTS & THRESHOLDS
    # =========================================================================
    path("stream/<str:stream>/inventory-alerts/", views.inventory_alerts_list, name="inventory_alerts_list"),
    path(
        "stream/<str:stream>/inventory-alerts/thresholds/",
        views.inventory_thresholds_list,
        name="inventory_thresholds_list",
    ),
    path(
        "stream/<str:stream>/inventory-alerts/thresholds/create/",
        views.inventory_threshold_create,
        name="inventory_threshold_create",
    ),
    path(
        "stream/<str:stream>/inventory-alerts/thresholds/<int:pk>/edit/",
        views.inventory_threshold_edit,
        name="inventory_threshold_edit",
    ),
    path(
        "stream/<str:stream>/inventory-alerts/thresholds/<int:pk>/delete/",
        views.inventory_threshold_delete,
        name="inventory_threshold_delete",
    ),
    path(
        "stream/<str:stream>/inventory-alerts/<int:pk>/acknowledge/",
        views.inventory_alert_acknowledge,
        name="inventory_alert_acknowledge",
    ),
    path(
        "stream/<str:stream>/inventory-alerts/<int:pk>/resolve/",
        views.inventory_alert_resolve,
        name="inventory_alert_resolve",
    ),
    path(
        "stream/<str:stream>/inventory-alerts/check-all/",
        views.inventory_check_all_thresholds,
        name="inventory_check_all_thresholds",
    ),
    # =========================================================================
    # FEATURE 5: FILE VERSIONING FOR COMPLIANCE DOCUMENTS
    # =========================================================================
    path(
        "stream/<str:stream>/compliance/documents/<int:pk>/versions/",
        views.compliance_document_versions,
        name="compliance_document_versions",
    ),
    path(
        "stream/<str:stream>/compliance/documents/<int:pk>/versions/upload/",
        views.compliance_document_version_upload,
        name="compliance_document_version_upload",
    ),
    path(
        "stream/<str:stream>/compliance/documents/<int:pk>/versions/<int:version_id>/restore/",
        views.compliance_document_version_restore,
        name="compliance_document_version_restore",
    ),
    path(
        "stream/<str:stream>/compliance/documents/<int:pk>/versions/<int:version_id>/download/",
        views.compliance_document_version_download,
        name="compliance_document_version_download",
    ),
    # =========================================================================
    # FEATURE 6: MAINTENANCE CALENDAR VIEW
    # =========================================================================
    path("maintenance-calendar/", views.maintenance_calendar, name="maintenance_calendar"),
    path("stream/<str:stream>/maintenance-calendar/", views.maintenance_calendar, name="maintenance_calendar_stream"),
    path(
        "api/maintenance-calendar/events/",
        views.maintenance_calendar_events_api,
        name="maintenance_calendar_events_api",
    ),
    path(
        "api/maintenance-calendar/events/create/",
        views.maintenance_event_create_api,
        name="maintenance_event_create_api",
    ),
    path(
        "api/maintenance-calendar/events/<int:pk>/update/",
        views.maintenance_event_update_api,
        name="maintenance_event_update_api",
    ),
    path(
        "api/maintenance-calendar/events/<int:pk>/delete/",
        views.maintenance_event_delete_api,
        name="maintenance_event_delete_api",
    ),
    path(
        "api/maintenance-calendar/events/<int:pk>/complete/",
        views.maintenance_event_complete_api,
        name="maintenance_event_complete_api",
    ),
    # =========================================================================
    # AI FEATURES — redirect bare /ai/ to feature hub
    # =========================================================================
    path("stream/<str:stream>/ai/", lambda request, stream: redirect("feature_hub"), name="ai_hub_redirect"),
    # =========================================================================
    # AI FEATURE 1: AUTO-GENERATE CALIBRATION REPORTS
    # =========================================================================
    path(
        "stream/<str:stream>/ai/calibration-reports/", views.ai_calibration_report_hub, name="ai_calibration_report_hub"
    ),
    path(
        "stream/<str:stream>/ai/calibration-reports/generate/<int:schedule_id>/",
        views.ai_calibration_report_generate,
        name="ai_calibration_report_generate",
    ),
    path(
        "stream/<str:stream>/ai/calibration-reports/<int:pk>/",
        views.ai_calibration_report_view,
        name="ai_calibration_report_view",
    ),
    path(
        "stream/<str:stream>/ai/calibration-reports/<int:pk>/pdf/",
        views.ai_calibration_report_pdf,
        name="ai_calibration_report_pdf",
    ),
    # =========================================================================
    # AI FEATURE 2: DOCUMENT OCR & AUTO-EXTRACTION
    # =========================================================================
    path("stream/<str:stream>/ai/ocr/", views.ai_ocr_hub, name="ai_ocr_hub"),
    path("stream/<str:stream>/ai/ocr/process/", views.ai_ocr_process, name="ai_ocr_process"),
    path("stream/<str:stream>/ai/ocr/result/<int:pk>/", views.ai_ocr_result, name="ai_ocr_result"),
    # =========================================================================
    # AI FEATURE 3: NATURAL LANGUAGE TO SQL DASHBOARD
    # =========================================================================
    path("stream/<str:stream>/ai/nl-dashboard/", views.ai_nl_dashboard, name="ai_nl_dashboard"),
    path("stream/<str:stream>/api/ai/nl-query/", views.ai_nl_query_api, name="ai_nl_query_api"),
    path("stream/<str:stream>/api/ai/nl-feedback/", views.ai_nl_feedback_api, name="ai_nl_feedback_api"),
    # =========================================================================
    # AI FEATURE 4: PREDICTIVE INVENTORY FORECASTING
    # =========================================================================
    path("stream/<str:stream>/ai/inventory-forecast/", views.ai_inventory_forecast, name="ai_inventory_forecast"),
    path(
        "stream/<str:stream>/ai/inventory-forecast/generate/",
        views.ai_inventory_forecast_generate,
        name="ai_inventory_forecast_generate",
    ),
    path(
        "stream/<str:stream>/ai/inventory-forecast/<int:pk>/",
        views.ai_inventory_forecast_view,
        name="ai_inventory_forecast_view",
    ),
    # =========================================================================
    # AI FEATURE 5: SMART RESERVATION SCHEDULING
    # =========================================================================
    path("stream/<str:stream>/ai/smart-scheduler/", views.ai_smart_scheduler, name="ai_smart_scheduler"),
    path(
        "stream/<str:stream>/ai/smart-scheduler/recommend/",
        views.ai_smart_scheduler_recommend,
        name="ai_smart_scheduler_recommend",
    ),
    # =========================================================================
    # AI: MODEL MANAGEMENT
    # =========================================================================
    path("stream/<str:stream>/ai/model-management/", views.ai_model_management, name="ai_model_management"),
    path("stream/<str:stream>/api/ai/train-model/", views.ai_train_model_api, name="ai_train_model_api"),
    # =========================================================================
    # AI FEATURE 6: USAGE PATTERN ANALYTICS
    # =========================================================================
    path("stream/<str:stream>/ai/usage-analytics/", views.ai_usage_analytics, name="ai_usage_analytics"),
    path(
        "stream/<str:stream>/ai/usage-analytics/generate/",
        views.ai_usage_analytics_generate,
        name="ai_usage_analytics_generate",
    ),
    path(
        "stream/<str:stream>/ai/usage-analytics/<int:pk>/",
        views.ai_usage_analytics_view,
        name="ai_usage_analytics_view",
    ),
    # =========================================================================
    # AI FEATURE 7: DUPLICATE / ANOMALY DETECTION
    # =========================================================================
    path("stream/<str:stream>/ai/anomaly-detection/", views.ai_anomaly_detection, name="ai_anomaly_detection"),
    path(
        "stream/<str:stream>/ai/anomaly-detection/scan/",
        views.ai_anomaly_detection_scan,
        name="ai_anomaly_detection_scan",
    ),
    path(
        "stream/<str:stream>/ai/anomaly-detection/<int:pk>/",
        views.ai_anomaly_detection_view,
        name="ai_anomaly_detection_view",
    ),
    # =========================================================================
    # HEALTH CHECK & VERSION (Public API — no auth required)
    # =========================================================================
    path("api/health/", views.health_check, name="health_check"),
    path("api/version/", views.version_info, name="version_info"),
    # =========================================================================
    # PAGE NAVIGATION — Back / Forward toolbar handler
    # =========================================================================
    path("page-nav/", views.page_nav_action, name="page_nav_action"),
    # =========================================================================
    # SITE SETTINGS
    # =========================================================================
    path("api/site-settings/", views.get_site_settings, name="get_site_settings"),
    path("api/site-settings/toggle-devtools/", views.toggle_devtools_protection, name="toggle_devtools_protection"),
    # =========================================================================
    # BU SHOWCASE PRODUCTS (Dashboard Product Gallery CRUD)
    # =========================================================================
    path("api/showcase-products/", views.showcase_products_api, name="showcase_products_api"),
    path("api/showcase-products/<int:pk>/update/", views.showcase_product_update, name="showcase_product_update"),
    path("api/showcase-products/<int:pk>/delete/", views.showcase_product_delete, name="showcase_product_delete"),
    # =========================================================================
    # LAB WASTE MANAGEMENT
    # =========================================================================
    path("waste-management/", views.waste_dashboard, name="waste_dashboard"),
    path("waste-management/<str:stream>/", views.waste_stream_detail, name="waste_stream_detail"),
    path("api/waste/records/create/", views.waste_record_create, name="waste_record_create"),
    path("api/waste/records/<int:pk>/", views.waste_record_detail_api, name="waste_record_detail_api"),
    path("api/waste/records/<int:pk>/update/", views.waste_record_update, name="waste_record_update"),
    path("api/waste/records/<int:pk>/delete/", views.waste_record_delete, name="waste_record_delete"),
    path("api/waste/categories/", views.waste_category_api, name="waste_category_api"),
    path("api/waste/categories/<int:pk>/delete/", views.waste_category_delete, name="waste_category_delete"),
    path("api/waste/schedules/create/", views.waste_schedule_create, name="waste_schedule_create"),
    path("api/waste/schedules/<int:pk>/", views.waste_schedule_detail_api, name="waste_schedule_detail_api"),
    path("api/waste/schedules/<int:pk>/update/", views.waste_schedule_update, name="waste_schedule_update"),
    path("api/waste/schedules/<int:pk>/delete/", views.waste_schedule_delete, name="waste_schedule_delete"),
    path("api/waste/schedules/<int:pk>/assign/", views.waste_schedule_assign, name="waste_schedule_assign"),
    path("api/waste/stats/", views.waste_stats_api, name="waste_stats_api"),
    path("waste-management/export/", views.waste_export, name="waste_export"),
    # =========================================================================
    # VENDOR / SUPPLIER MANAGEMENT
    # =========================================================================
    path("vendors/", views.vendor_hub, name="vendor_hub"),
    path("stream/<str:stream>/vendors/", views.vendor_list, name="vendor_list"),
    path("stream/<str:stream>/vendors/analytics/", views.vendor_analytics_api, name="vendor_analytics_api"),
    path("stream/<str:stream>/vendors/create/", views.vendor_create, name="vendor_create"),
    path("stream/<str:stream>/vendors/<int:pk>/", views.vendor_detail, name="vendor_detail"),
    path("stream/<str:stream>/vendors/<int:pk>/edit/", views.vendor_edit, name="vendor_edit"),
    path("stream/<str:stream>/vendors/<int:pk>/delete/", views.vendor_delete, name="vendor_delete"),
    path(
        "stream/<str:stream>/vendors/<int:vendor_id>/contracts/create/",
        views.vendor_contract_create,
        name="vendor_contract_create",
    ),
    path(
        "stream/<str:stream>/vendors/<int:vendor_id>/contracts/<int:pk>/delete/",
        views.vendor_contract_delete,
        name="vendor_contract_delete",
    ),
    path(
        "stream/<str:stream>/vendors/<int:vendor_id>/performance/create/",
        views.vendor_performance_log_create,
        name="vendor_performance_log_create",
    ),
    path("stream/<str:stream>/vendors/export/", views.vendor_export, name="vendor_export"),
    # Purchase Orders
    path("stream/<str:stream>/vendors/<int:vendor_id>/po/create/", views.vendor_po_create, name="vendor_po_create"),
    path(
        "stream/<str:stream>/vendors/<int:vendor_id>/po/<int:po_id>/", views.vendor_po_detail, name="vendor_po_detail"
    ),
    path(
        "stream/<str:stream>/vendors/<int:vendor_id>/po/<int:po_id>/status/",
        views.vendor_po_update_status,
        name="vendor_po_update_status",
    ),
    path(
        "stream/<str:stream>/vendors/<int:vendor_id>/po/<int:po_id>/receive/",
        views.vendor_po_receive,
        name="vendor_po_receive",
    ),
    path(
        "stream/<str:stream>/vendors/<int:vendor_id>/po/<int:po_id>/delete/",
        views.vendor_po_delete,
        name="vendor_po_delete",
    ),
    # =========================================================================
    # TEAM CHAT / COLLABORATION
    # =========================================================================
    path("team-chat/", views.team_chat, name="team_chat"),
    path("team-chat/room/<int:room_id>/", views.chat_room_view, name="chat_room_view"),
    path("team-chat/room/<int:room_id>/api/", views.chat_api, name="chat_api"),
    path("team-chat/room/<int:room_id>/upload/", views.chat_upload_attachment, name="chat_upload_attachment"),
    path("team-chat/room/<int:room_id>/react/<int:message_id>/", views.chat_react, name="chat_react"),
    path("team-chat/room/<int:room_id>/pin/<int:message_id>/", views.chat_pin_message, name="chat_pin_message"),
    path("team-chat/room/<int:room_id>/typing/", views.chat_typing_indicator, name="chat_typing_indicator"),
    path("team-chat/room/<int:room_id>/add-member/", views.group_chat_add_member, name="group_chat_add_member"),
    path(
        "team-chat/room/<int:room_id>/remove-member/<int:user_id>/",
        views.group_chat_remove_member,
        name="group_chat_remove_member",
    ),
    path("team-chat/create-room/", views.chat_room_create, name="chat_room_create"),
    # =========================================================================
    # TLD BADGE MANAGEMENT
    # =========================================================================
    path("tld-badges/", views.tld_badge_dashboard, name="tld_badge_dashboard"),
    path("api/tld-badges/create/", views.tld_badge_create, name="tld_badge_create"),
    path("api/tld-badges/<int:pk>/edit/", views.tld_badge_edit, name="tld_badge_edit"),
    path("api/tld-badges/<int:pk>/delete/", views.tld_badge_delete, name="tld_badge_delete"),
    path("tld-badges/export/", views.tld_badge_export, name="tld_badge_export"),
    path("api/tld-badges/bulk-import/", views.tld_badge_bulk_import, name="tld_badge_bulk_import"),
    path("api/tld-badges/bulk-update/", views.tld_badge_bulk_update, name="tld_badge_bulk_update"),
    path("api/tld-badges/check-duplicate/", views.tld_badge_check_duplicate, name="tld_badge_check_duplicate"),
    path("api/tld-badges/<int:pk>/history/", views.tld_badge_history, name="tld_badge_history"),
    path("api/tld-badges/audit-log/", views.tld_badge_audit_log, name="tld_badge_audit_log"),
    path("api/tld-badges/print/", views.tld_badge_print, name="tld_badge_print"),
    # =========================================================================
    # FEATURE ACCESS CONTROL (App Admin)
    # =========================================================================
    path("feature-access-control/", views.feature_access_control, name="feature_access_control"),
    path("api/feature-access/toggle/", views.feature_access_toggle, name="feature_access_toggle"),
    path("api/feature-access/bulk-toggle/", views.feature_access_bulk_toggle, name="feature_access_bulk_toggle"),
    path("api/feature-access/export/", views.feature_access_export, name="feature_access_export"),
    path("api/feature-access/import/", views.feature_access_import, name="feature_access_import"),
    path("api/feature-access/reset/", views.feature_access_reset, name="feature_access_reset"),
    path("api/feature-access/copy-role/", views.feature_access_copy_role, name="feature_access_copy_role"),
    path("api/feature-access/history/", views.feature_access_history, name="feature_access_history"),
    path("api/feature-access/compare/", views.feature_access_compare, name="feature_access_compare"),
    path("api/feature-access/summary/", views.feature_access_summary, name="feature_access_summary"),
    # =========================================================================
    # APPROVAL WORKFLOWS ENGINE
    # =========================================================================
    path("approvals/", views.approval_dashboard, name="approval_dashboard"),
    path("approvals/api/templates/", views.approval_templates_api, name="approval_templates_api"),
    path(
        "approvals/api/templates/<int:template_id>/",
        views.approval_template_detail_api,
        name="approval_template_detail_api",
    ),
    path("approvals/api/request/create/", views.approval_request_create, name="approval_request_create"),
    path(
        "approvals/api/request/<int:request_id>/",
        views.approval_request_detail,
        name="approval_request_detail",
    ),
    path(
        "approvals/api/request/<int:request_id>/action/",
        views.approval_request_action,
        name="approval_request_action",
    ),
    path(
        "approvals/api/request/<int:request_id>/comment/",
        views.approval_request_comment,
        name="approval_request_comment",
    ),
    path("approvals/api/my-pending/", views.approval_my_pending, name="approval_my_pending"),
    path("approvals/api/analytics/", views.approval_analytics_api, name="approval_analytics_api"),
    path("approvals/api/triggers/", views.approval_triggers_api, name="approval_triggers_api"),
    path(
        "approvals/api/triggers/<int:trigger_id>/",
        views.approval_trigger_detail_api,
        name="approval_trigger_detail_api",
    ),
    path("approvals/api/entity-types/", views.approval_entity_types_api, name="approval_entity_types_api"),
    path("approvals/api/event-types/", views.approval_event_types_api, name="approval_event_types_api"),
    # =========================================================================
    # GLOBAL FULL-TEXT SEARCH
    # =========================================================================
    path("search/", views.global_search, name="global_search"),
    path("search/api/search/", views.global_search_api, name="global_search_api"),
    path("search/api/suggestions/", views.search_suggestions_api, name="search_suggestions_api"),
    path("search/api/reindex/", views.search_reindex_api, name="search_reindex_api"),
    path("search/api/log-click/", views.search_log_click_api, name="search_log_click_api"),
    # =========================================================================
    # SHIFT HANDOVER LOG
    # =========================================================================
    path("shift-handover/", views.shift_handover_hub, name="shift_handover_hub"),
    path("shift-handover/<str:stream>/", views.shift_handover_stream, name="shift_handover_stream"),
    path("api/shift-handover/create/", views.shift_handover_create, name="shift_handover_create"),
    path("api/shift-handover/<int:pk>/", views.shift_handover_detail_api, name="shift_handover_detail_api"),
    path("api/shift-handover/<int:pk>/update/", views.shift_handover_update, name="shift_handover_update"),
    path("api/shift-handover/<int:pk>/delete/", views.shift_handover_delete, name="shift_handover_delete"),
    path("api/shift-handover/<int:pk>/submit/", views.shift_handover_submit, name="shift_handover_submit"),
    path("api/shift-handover/<int:pk>/acknowledge/", views.shift_handover_acknowledge, name="shift_handover_acknowledge"),
    path("api/shift-handover/<int:pk>/comment/", views.shift_handover_comment, name="shift_handover_comment"),
    path("api/shift-handover/stats/", views.shift_handover_stats_api, name="shift_handover_stats_api"),
    path("api/shift-types/", views.shift_type_api, name="shift_type_api"),
    path("api/shift-types/<int:pk>/delete/", views.shift_type_delete, name="shift_type_delete"),
    # =========================================================================\n    # DEMO REQUESTS & VULNERABILITY REPORTS (Public submit + Admin management)\n    # =========================================================================
    path("api/demo-request/submit/", views.submit_demo_request, name="submit_demo_request"),
    path("api/vulnerability-report/submit/", views.submit_vulnerability_report, name="submit_vulnerability_report"),
    path("public-requests/", views.public_requests_list, name="public_requests_list"),
    path("api/demo-request/<int:pk>/update/", views.demo_request_update_status, name="demo_request_update_status"),
    path("api/vulnerability-report/<int:pk>/update/", views.vulnerability_report_update_status, name="vulnerability_report_update_status"),
    path("api/public-request/send-email/", views.send_public_request_email, name="send_public_request_email"),
] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
