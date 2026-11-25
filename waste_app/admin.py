from django.contrib import admin

from .models import (
    CompostBatch,
    CompostProduct,
    CollectionRoute,
    CollectionZone,
    LocationUpdate,
    PickupRequest,
    RecyclingRecord,
    RouteStop,
    SalesOrder,
    UserProfile,
    UserNotification,
    Vehicle,
    WasteCategory,
)


@admin.register(CompostBatch)
class CompostBatchAdmin(admin.ModelAdmin):
    list_display = ('batch_code', 'input_weight_kg', 'yield_kg', 'status', 'ready_at')
    list_filter = ('status', 'created_at')
    search_fields = ('batch_code', 'notes')
    filter_horizontal = ('source_pickups',)


@admin.register(CompostProduct)
class CompostProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'price_per_kg', 'stock_kg', 'is_active', 'compost_batch')
    list_filter = ('is_active',)
    search_fields = ('name', 'description')


@admin.register(SalesOrder)
class SalesOrderAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'product',
        'quantity_kg',
        'total_amount',
        'status',
        'created_at',
    )
    list_filter = ('status', 'created_at')
    search_fields = ('user__email', 'product__name')
    list_select_related = ('user', 'product')


@admin.register(UserNotification)
class UserNotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'category', 'title', 'is_read', 'created_at')
    list_filter = ('category', 'is_read', 'created_at')
    search_fields = ('recipient__email', 'title', 'message')


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone', 'eco_points')
    search_fields = ('user__username', 'user__email', 'phone')


@admin.register(WasteCategory)
class WasteCategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'points_per_kg', 'is_recyclable', 'description')


@admin.register(CollectionZone)
class CollectionZoneAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'area_description')


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = (
        'vehicle_code',
        'capacity_kg',
        'operator_name',
        'status',
        'current_checkpoint',
        'location_updated_at',
    )
    list_filter = ('status',)
    search_fields = ('vehicle_code', 'operator_name', 'current_checkpoint')


@admin.register(CollectionRoute)
class CollectionRouteAdmin(admin.ModelAdmin):
    list_display = ('name', 'zone', 'vehicle', 'scheduled_date', 'status')
    list_filter = ('status', 'zone', 'scheduled_date')
    search_fields = ('name', 'zone__name', 'vehicle__vehicle_code')
    list_select_related = ('zone', 'vehicle')


@admin.register(RouteStop)
class RouteStopAdmin(admin.ModelAdmin):
    list_display = ('route', 'stop_order', 'pickup', 'status')
    list_filter = ('status', 'route__scheduled_date', 'route__zone')
    search_fields = ('route__name', 'pickup__user__email', 'pickup__pickup_address')
    list_select_related = ('route', 'pickup', 'pickup__user')


@admin.register(LocationUpdate)
class LocationUpdateAdmin(admin.ModelAdmin):
    list_display = ('route', 'checkpoint', 'route_status', 'created_by', 'created_at')
    list_filter = ('route_status', 'created_at')
    search_fields = ('route__name', 'checkpoint', 'notes')
    list_select_related = ('route', 'created_by')


@admin.register(RecyclingRecord)
class RecyclingRecordAdmin(admin.ModelAdmin):
    list_display = (
        'pickup',
        'classification',
        'sorted_weight_kg',
        'stage',
        'eco_points_awarded',
        'updated_at',
    )
    list_filter = ('classification', 'stage')
    search_fields = ('pickup__user__email', 'pickup__pickup_address', 'notes')
    list_select_related = ('pickup', 'pickup__user', 'pickup__category')


@admin.register(PickupRequest)
class PickupRequestAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'category',
        'pickup_date',
        'time_slot',
        'estimated_weight_kg',
        'customer_type',
        'customer_tier',
        'status',
        'created_at',
    )
    list_filter = ('status', 'category', 'pickup_date')
    search_fields = ('user__username', 'user__first_name', 'user__email', 'pickup_address')
    list_select_related = ('user', 'category')
