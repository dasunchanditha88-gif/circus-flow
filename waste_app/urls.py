from django.urls import path

from . import views


urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.login, name='login'),
    path('register/', views.register, name='register'),
    path('logout/', views.logout, name='logout'),
    path('dashboard/', views.user_dashboard, name='user_dashboard'),
    path('dashboard/cancel/<int:pickup_id>/', views.cancel_pickup, name='cancel_pickup'),
    path('profile/', views.profile, name='profile'),
    path('guidelines/', views.guidelines, name='guidelines'),
    path('admin-panel/', views.admin_dashboard, name='admin_dashboard'),
    path('admin-panel/dispatch/', views.dispatch_dashboard, name='dispatch_dashboard'),
    path('admin-panel/compost/', views.compost_management, name='compost_management'),
    path('admin-panel/compost/create/', views.create_compost_batch, name='create_compost_batch'),
    path(
        'admin-panel/compost/<int:batch_id>/',
        views.update_compost_batch,
        name='update_compost_batch',
    ),
    path('admin-panel/sales/', views.sales_management, name='sales_management'),
    path('admin-panel/sales/products/create/', views.create_compost_product, name='create_compost_product'),
    path(
        'admin-panel/sales/products/<int:product_id>/',
        views.update_compost_product,
        name='update_compost_product',
    ),
    path(
        'admin-panel/sales/orders/<int:order_id>/status/',
        views.update_sales_order,
        name='update_sales_order',
    ),
    path('admin-panel/reports/', views.reports, name='reports'),
    path(
        'admin-panel/customers/<int:user_id>/access/',
        views.update_customer_access,
        name='update_customer_access',
    ),
    path('marketplace/', views.marketplace, name='marketplace'),
    path('marketplace/orders/<int:order_id>/cancel/', views.cancel_sales_order, name='cancel_sales_order'),
    path('notifications/', views.notifications, name='notifications'),
    path(
        'notifications/<int:notification_id>/read/',
        views.mark_notification_read,
        name='mark_notification_read',
    ),
    path(
        'notifications/read-all/',
        views.mark_all_notifications_read,
        name='mark_all_notifications_read',
    ),
    path('admin-panel/vehicles/create/', views.create_vehicle, name='create_vehicle'),
    path(
        'admin-panel/vehicles/<int:vehicle_id>/status/',
        views.update_vehicle_status,
        name='update_vehicle_status',
    ),
    path('admin-panel/zones/create/', views.create_zone, name='create_zone'),
    path(
        'admin-panel/zones/<int:zone_id>/',
        views.update_zone,
        name='update_zone',
    ),
    path('admin-panel/routes/create/', views.create_route, name='create_route'),
    path(
        'admin-panel/routes/assign-stop/',
        views.assign_route_stop,
        name='assign_route_stop',
    ),
    path(
        'admin-panel/routes/location-update/',
        views.add_location_update,
        name='add_location_update',
    ),
    path(
        'admin-panel/recycling/<int:pickup_id>/',
        views.update_recycling_record,
        name='update_recycling_record',
    ),
    path('admin-panel/categories/create/', views.create_category, name='create_category'),
    path(
        'admin-panel/categories/<int:category_id>/',
        views.update_category,
        name='update_category',
    ),
    path(
        'admin-panel/status/<int:pickup_id>/',
        views.update_pickup_status,
        name='update_pickup_status',
    ),
]
