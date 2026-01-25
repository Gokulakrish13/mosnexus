from django.contrib import admin
from .models import Product, ProductHistory, Category, SubLevel, SubLevelHistory, SubLevelTool, SubLevelToolHistory, SystemTag, Project, HolisticSystem, HolisticWeeklyData, HolisticSystemHistory, Note, NoteAttachment, SharedNote, BuildServer, BuildServerHistory, BuildServerMaintenanceLog, Floor, OperatingSystem

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'serial_number', 'category', 'created_at')
    search_fields = ('name', 'serial_number')
    list_filter = ('category',)

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'serial_number', 'created_at')
    search_fields = ('name', 'serial_number')

@admin.register(ProductHistory)
class ProductHistoryAdmin(admin.ModelAdmin):
    list_display = ('product', 'action', 'user', 'timestamp')
    search_fields = ('product__name', 'user__username', 'action')

@admin.register(SubLevel)
class SubLevelAdmin(admin.ModelAdmin):
    list_display = ('name', 'stream', 'in_stock', 'in_use', 'scraped')
    search_fields = ('name', 'stream')
    list_filter = ('stream',)

@admin.register(SubLevelHistory)
class SubLevelHistoryAdmin(admin.ModelAdmin):
    list_display = ('sublevel', 'action', 'by', 'at')
    search_fields = ('sublevel__name', 'by', 'action')

@admin.register(SubLevelTool)
class SubLevelToolAdmin(admin.ModelAdmin):
    list_display = ('name', 'stream', 'in_stock', 'in_use', 'scraped')
    search_fields = ('name', 'stream')
    list_filter = ('stream',)

@admin.register(SubLevelToolHistory)
class SubLevelToolHistoryAdmin(admin.ModelAdmin):
    list_display = ('subleveltool', 'action', 'by', 'at')
    search_fields = ('subleveltool__name', 'by', 'action')

@admin.register(SystemTag)
class SystemTagAdmin(admin.ModelAdmin):
    list_display = ('tag_name', 'system', 'stream', 'created_by', 'created_at', 'get_components_count')
    search_fields = ('tag_name', 'system__name', 'description')
    list_filter = ('stream', 'system', 'created_at')
    filter_horizontal = ('products', 'sublevels', 'sublevel_tools')
    readonly_fields = ('created_at', 'created_by')
    
    def get_components_count(self, obj):
        return obj.get_all_components_count()
    get_components_count.short_description = 'Total Components'
    
    def save_model(self, request, obj, form, change):
        if not change:  # If creating new object
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'priority', 'start_date', 'initial_release_date', 'final_release_date', 'progress_percentage', 'expected_progress', 'stream', 'created_by', 'created_at')
    search_fields = ('name', 'description', 'created_by__username')
    list_filter = ('status', 'priority', 'stream', 'created_at', 'start_date', 'initial_release_date', 'final_release_date')
    filter_horizontal = ('team_members',)
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'start_date'
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'stream')
        }),
        ('Timeline', {
            'fields': ('duration', 'start_date', 'initial_release_date', 'final_release_date')
        }),
        ('Status & Priority', {
            'fields': ('status', 'priority', 'progress_percentage', 'expected_progress')
        }),
        ('Team', {
            'fields': ('team_members', 'created_by')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if not change:  # If creating new object
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(HolisticSystem)
class HolisticSystemAdmin(admin.ModelAdmin):
    list_display = ('sr_no', 'system_availability', 'allocation_to_sl_no', 'location_info', 'system_owner', 'test_engineer', 'priority', 'stream', 'created_at')
    search_fields = ('sr_no', 'system_owner', 'test_engineer', 'stmi_number', 'ecr_number', 'location_info')
    list_filter = ('system_availability', 'priority', 'stream', 'created_at')
    readonly_fields = ('created_at', 'updated_at', 'created_by', 'updated_by')
    
    fieldsets = (
        ('Core Information', {
            'fields': ('sr_no', 'system_availability', 'allocation_to_sl_no', 'stream')
        }),
        ('System Details', {
            'fields': ('location_info', 'stmi_number', 'system_owner', 'ecr_number', 'test_engineer')
        }),
        ('Additional Information', {
            'fields': ('description', 'notes', 'priority')
        }),
        ('Metadata', {
            'fields': ('created_at', 'created_by', 'updated_at', 'updated_by'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(HolisticWeeklyData)
class HolisticWeeklyDataAdmin(admin.ModelAdmin):
    list_display = ('holistic_system', 'get_week_label', 'year', 'allocation_status', 'utilization_percentage', 'assigned_to', 'hours_used')
    search_fields = ('holistic_system__sr_no', 'allocation_status', 'assigned_to')
    list_filter = ('year', 'week_number', 'holistic_system__stream')
    readonly_fields = ('created_at', 'updated_at', 'updated_by')
    
    fieldsets = (
        ('Time Period', {
            'fields': ('holistic_system', 'week_number', 'year')
        }),
        ('Weekly Metrics', {
            'fields': ('allocation_status', 'utilization_percentage', 'assigned_to', 'hours_used', 'availability_hours')
        }),
        ('Details', {
            'fields': ('task_description', 'notes')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at', 'updated_by'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(HolisticSystemHistory)
class HolisticSystemHistoryAdmin(admin.ModelAdmin):
    list_display = ('holistic_system', 'action', 'user', 'timestamp')
    search_fields = ('holistic_system__sr_no', 'action', 'user__username')
    list_filter = ('action', 'timestamp')
    readonly_fields = ('timestamp',)

@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ('title', 'created_by', 'is_public', 'created_at', 'updated_at')
    search_fields = ('title', 'content', 'created_by__username')
    list_filter = ('is_public', 'created_at', 'updated_at')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Note Information', {
            'fields': ('title', 'content', 'is_public')
        }),
        ('Meta Information', {
            'fields': ('created_by', 'updated_by', 'created_at', 'updated_at')
        }),
    )

@admin.register(NoteAttachment)
class NoteAttachmentAdmin(admin.ModelAdmin):
    list_display = ('note', 'original_filename', 'file_type', 'file_size', 'uploaded_by', 'uploaded_at')
    search_fields = ('note__title', 'original_filename', 'uploaded_by__username')
    list_filter = ('file_type', 'uploaded_at')
    readonly_fields = ('uploaded_at', 'file_size', 'content_type')

@admin.register(SharedNote)
class SharedNoteAdmin(admin.ModelAdmin):
    list_display = ('note', 'shared_by', 'shared_with', 'shared_at', 'is_read')
    search_fields = ('note__title', 'shared_by__username', 'shared_with__username')
    list_filter = ('shared_at', 'is_read')
    readonly_fields = ('shared_at',)
    
    fieldsets = (
        ('Share Information', {
            'fields': ('note', 'shared_by', 'shared_with', 'message')
        }),
        ('Status', {
            'fields': ('is_read', 'shared_at')
        }),
    )

# Build Server Admin
@admin.register(BuildServer)
class BuildServerAdmin(admin.ModelAdmin):
    list_display = ('hostname', 'ip_address', 'stream_type', 'location', 'floor', 'owner', 'status', 'created_at')
    list_filter = ('stream_type', 'status', 'floor', 'stream', 'created_at')
    search_fields = ('hostname', 'ip_address', 'location', 'owner', 'purpose')
    readonly_fields = ('created_at', 'created_by', 'updated_at', 'updated_by')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('hostname', 'ip_address', 'stream_type', 'stream', 'status')
        }),
        ('Location Details', {
            'fields': ('location', 'floor', 'owner')
        }),
        ('Hardware Specifications', {
            'fields': ('operating_system', 'cpu_cores', 'ram_gb', 'storage_gb'),
            'classes': ('collapse',)
        }),
        ('Network Details', {
            'fields': ('mac_address', 'domain', 'ssh_port'),
            'classes': ('collapse',)
        }),
        ('Business Information', {
            'fields': ('purpose', 'project_allocation', 'cost_center', 'procurement_date', 'warranty_expiry'),
            'classes': ('collapse',)
        }),
        ('Contact Information', {
            'fields': ('primary_contact', 'secondary_contact', 'contact_email'),
            'classes': ('collapse',)
        }),
        ('Maintenance', {
            'fields': ('last_maintenance', 'next_maintenance', 'uptime_percentage'),
            'classes': ('collapse',)
        }),
        ('Additional Information', {
            'fields': ('notes', 'tags'),
            'classes': ('collapse',)
        }),
        ('Tracking', {
            'fields': ('created_at', 'created_by', 'updated_at', 'updated_by'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        if not change:  # Creating new object
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(BuildServerHistory)
class BuildServerHistoryAdmin(admin.ModelAdmin):
    list_display = ('build_server', 'action', 'user', 'timestamp', 'get_hostname')
    list_filter = ('action', 'timestamp')
    search_fields = ('build_server__hostname', 'user__username', 'action')
    readonly_fields = ('timestamp',)
    
    def get_hostname(self, obj):
        return obj.build_server.hostname
    get_hostname.short_description = 'Hostname'

@admin.register(BuildServerMaintenanceLog)
class BuildServerMaintenanceLogAdmin(admin.ModelAdmin):
    list_display = ('build_server', 'maintenance_type', 'scheduled_date', 'completed', 'performed_by', 'cost')
    list_filter = ('maintenance_type', 'completed', 'scheduled_date', 'performed_by')
    search_fields = ('build_server__hostname', 'description', 'performed_by', 'vendor')
    date_hierarchy = 'scheduled_date'
    
    fieldsets = (
        ('Maintenance Information', {
            'fields': ('build_server', 'maintenance_type', 'scheduled_date', 'actual_date', 'completed')
        }),
        ('Details', {
            'fields': ('description', 'performed_by', 'duration_hours', 'authorized_by')
        }),
        ('Issues & Follow-up', {
            'fields': ('issues_found', 'actions_taken', 'parts_replaced', 'requires_followup', 'next_maintenance_due'),
            'classes': ('collapse',)
        }),
        ('Cost Information', {
            'fields': ('cost', 'vendor'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

# Register your models here.\n\n@admin.register(Floor)\nclass FloorAdmin(admin.ModelAdmin):\n    list_display = ('name', 'description', 'is_active', 'created_at')\n    search_fields = ('name', 'description')\n    list_filter = ('is_active', 'created_at')\n    readonly_fields = ('created_at', 'updated_at')
@admin.register(OperatingSystem)
class OperatingSystemAdmin(admin.ModelAdmin):
    list_display = ('name', 'version', 'stream', 'is_active', 'created_at')
    search_fields = ('name', 'version', 'description')
    list_filter = ('stream', 'is_active', 'created_at')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ['stream', 'name', 'version']
