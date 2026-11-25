from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.db.models import Count, F, Prefetch, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    CompostBatchForm,
    CompostProductForm,
    CollectionRouteForm,
    CollectionZoneForm,
    CollectionZoneUpdateForm,
    EmailAuthenticationForm,
    LocationUpdateForm,
    PickupRequestForm,
    PickupStatusFilterForm,
    ProfileUpdateForm,
    RecyclingRecordForm,
    RegistrationForm,
    RouteStopForm,
    SalesOrderForm,
    VehicleForm,
    WasteCategoryForm,
)
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


def home(request):
    total_diverted_weight = (
        PickupRequest.objects.filter(status=PickupRequest.Status.COMPLETED)
        .aggregate(total=Sum('estimated_weight_kg'))['total']
        or Decimal('0')
    )
    return render(
        request,
        'waste_app/home.html',
        {
            'categories': WasteCategory.objects.all(),
            'total_diverted_weight': total_diverted_weight,
        },
    )


def _create_notification(recipient, category, title, message, pickup=None, order=None):
    return UserNotification.objects.create(
        recipient=recipient,
        category=category,
        title=title,
        message=message,
        pickup=pickup,
        order=order,
    )


def login(request):
    form = EmailAuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        auth_login(request, user)
        if not form.cleaned_data['remember']:
            request.session.set_expiry(0)
        return redirect('admin_dashboard' if user.is_staff or user.is_superuser else 'user_dashboard')
    return render(request, 'waste_app/login.html', {'form': form})


def register(request):
    form = RegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        user.backend = 'django.contrib.auth.backends.ModelBackend'
        auth_login(request, user)
        messages.success(request, 'Your Circus Flow account is ready.')
        return redirect('user_dashboard')
    return render(request, 'waste_app/register.html', {'form': form})


@require_POST
def logout(request):
    auth_logout(request)
    return redirect('home')


def _tracking_details(pickups):
    active_statuses = (
        PickupRequest.Status.PENDING,
        PickupRequest.Status.APPROVED,
    )
    tracking_pickup = pickups.filter(status__in=active_statuses).first()
    if tracking_pickup is None:
        tracking_pickup = pickups.first()

    latest_location = None
    if tracking_pickup:
        try:
            latest_location = tracking_pickup.route_stop.route.location_updates.first()
        except RouteStop.DoesNotExist:
            pass
    return tracking_pickup, latest_location


@login_required(login_url='login')
def user_dashboard(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    form = PickupRequestForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        pickup = form.save(user=request.user)
        _create_notification(
            request.user,
            UserNotification.Category.SCHEDULE,
            'Pickup scheduled',
            f'Your {pickup.category.name} pickup is scheduled for '
            f'{pickup.pickup_date:%b %d, %Y} ({pickup.time_slot}).',
            pickup=pickup,
        )
        messages.success(request, 'Your pickup request has been submitted.')
        return redirect('user_dashboard')

    requests = PickupRequest.objects.filter(user=request.user).select_related(
        'category',
        'zone',
        'route_stop__route__zone',
        'route_stop__route__vehicle',
        'recycling_record',
    ).prefetch_related('route_stop__route__location_updates')
    filter_form = PickupStatusFilterForm(request.GET or None)
    selected_status = ''
    if filter_form.is_bound:
        if filter_form.is_valid():
            selected_status = filter_form.cleaned_data['status']
        else:
            messages.error(request, 'Choose a valid pickup status filter.')

    history_requests = requests.select_related('category')
    if selected_status:
        history_requests = history_requests.filter(status=selected_status)
    completed_weight = (
        requests.filter(status=PickupRequest.Status.COMPLETED)
        .aggregate(total=Sum('estimated_weight_kg'))['total']
        or Decimal('0')
    )
    tracking_pickup, tracking_location = _tracking_details(requests)
    context = {
        'profile': profile,
        'form': form,
        'categories': WasteCategory.objects.order_by('name'),
        'zones': CollectionZone.objects.filter(is_active=True).order_by('name'),
        'pickup_requests': history_requests,
        'tracking_pickup': tracking_pickup,
        'tracking_location': tracking_location,
        'total_pickups': requests.count(),
        'pending_requests': requests.filter(status=PickupRequest.Status.PENDING).count(),
        'recycled_weight': completed_weight,
        'default_pickup_date': timezone.localdate(),
        'history_statuses': (('', 'All statuses'), *PickupRequest.Status.choices),
        'history_status': selected_status,
        'unread_notification_count': request.user.notifications.filter(
            is_read=False,
        ).count(),
    }
    return render(request, 'waste_app/user_dashboard.html', context)


@login_required(login_url='login')
def profile(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    initial = {
        'full_name': request.user.get_full_name() or request.user.username,
        'phone': profile.phone,
        'address': profile.address,
    }
    form = ProfileUpdateForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        form.save(request.user, profile)
        messages.success(request, 'Your profile has been updated.')
        return redirect('profile')

    completed_requests = PickupRequest.objects.filter(
        user=request.user,
        status=PickupRequest.Status.COMPLETED,
    )
    completed_weight = (
        completed_requests.aggregate(total=Sum('estimated_weight_kg'))['total']
        or Decimal('0')
    )
    return render(
        request,
        'waste_app/profile.html',
        {
            'form': form,
            'profile': profile,
            'completed_pickups': completed_requests.count(),
            'completed_weight': completed_weight,
            'unread_notification_count': request.user.notifications.filter(
                is_read=False,
            ).count(),
        },
    )


@login_required(login_url='login')
@require_POST
def cancel_pickup(request, pickup_id):
    with transaction.atomic():
        pickup = get_object_or_404(
            PickupRequest.objects.select_for_update(),
            pk=pickup_id,
            user=request.user,
        )
        if pickup.status not in (
            PickupRequest.Status.PENDING,
            PickupRequest.Status.APPROVED,
        ):
            messages.error(request, 'Only pending or approved requests can be cancelled.')
        else:
            pickup.status = PickupRequest.Status.CANCELLED
            pickup.save(update_fields=['status'])
            _create_notification(
                request.user,
                UserNotification.Category.STATUS,
                'Pickup cancelled',
                f'Pickup request #{pickup.pk} was cancelled.',
                pickup=pickup,
            )
            stop = RouteStop.objects.filter(pickup=pickup).first()
            if stop:
                stop.status = RouteStop.Status.SKIPPED
                stop.save(update_fields=['status'])
                _close_route_if_finished(stop.route_id)
            messages.success(request, 'Your pickup request was cancelled.')
    return redirect('user_dashboard')


@login_required(login_url='login')
def guidelines(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    user_pickups = PickupRequest.objects.filter(user=request.user).select_related(
        'category',
        'zone',
        'route_stop__route__zone',
        'route_stop__route__vehicle',
        'recycling_record',
    )
    tracking_pickup, tracking_location = _tracking_details(user_pickups)
    latest_request = (
        user_pickups
        .select_related(
            'category',
            'zone',
            'route_stop__route__zone',
            'route_stop__route__vehicle',
            'recycling_record',
        )
        .first()
    )
    latest_location = None
    latest_recycling_record = None
    if latest_request:
        try:
            latest_location = latest_request.route_stop.route.location_updates.first()
        except RouteStop.DoesNotExist:
            pass
        try:
            latest_recycling_record = latest_request.recycling_record
        except RecyclingRecord.DoesNotExist:
            pass
    lifecycle_progress = {
        PickupRequest.Status.PENDING: 25,
        PickupRequest.Status.APPROVED: 55,
        PickupRequest.Status.COMPLETED: 100,
        PickupRequest.Status.REJECTED: 100,
        PickupRequest.Status.CANCELLED: 100,
    }
    return render(
        request,
        'waste_app/guidelines.html',
        {
            'profile': profile,
            'latest_request': latest_request,
            'latest_location': latest_location,
            'latest_recycling_record': latest_recycling_record,
            'tracking_pickup': tracking_pickup,
            'tracking_location': tracking_location,
            'lifecycle_progress': (
                lifecycle_progress.get(latest_request.status, 0)
                if latest_request
                else 0
            ),
            'unread_notification_count': request.user.notifications.filter(
                is_read=False,
            ).count(),
        },
    )


def staff_required(user):
    return user.is_active and (user.is_staff or user.is_superuser)


def _close_route_if_finished(route_id):
    route = get_object_or_404(
        CollectionRoute.objects.select_for_update().select_related('vehicle'),
        pk=route_id,
    )
    if route.stops.exclude(
        status__in=(RouteStop.Status.COLLECTED, RouteStop.Status.SKIPPED),
    ).exists():
        return
    has_collected_stops = route.stops.filter(status=RouteStop.Status.COLLECTED).exists()
    route.status = (
        CollectionRoute.Status.COMPLETED
        if has_collected_stops
        else CollectionRoute.Status.CANCELLED
    )
    route.save(update_fields=['status'])
    if route.vehicle and route.vehicle.status == Vehicle.Status.ON_ROUTE:
        route.vehicle.status = Vehicle.Status.AVAILABLE
        route.vehicle.save(update_fields=['status'])


@user_passes_test(staff_required, login_url='login')
def admin_dashboard(request):
    today = timezone.localdate()
    pickup_requests = PickupRequest.objects.select_related(
        'user',
        'user__profile',
        'category',
        'zone',
        'route_stop__route__zone',
        'route_stop__route__vehicle',
        'recycling_record',
    ).prefetch_related('route_stop__route__location_updates')
    total_waste = (
        pickup_requests.filter(status=PickupRequest.Status.COMPLETED)
        .aggregate(total=Sum('estimated_weight_kg'))['total']
        or Decimal('0')
    )
    context = {
        'total_users': get_user_model().objects.count(),
        'on_route_vehicles': Vehicle.objects.filter(
            status=Vehicle.Status.ON_ROUTE,
        ).count(),
        'pending_pickups': pickup_requests.filter(status=PickupRequest.Status.PENDING).count(),
        'completed_today': pickup_requests.filter(
            status=PickupRequest.Status.COMPLETED,
            completed_at__date=today,
        ).count(),
        'total_waste_collected': total_waste,
        'compost_batches_in_progress': CompostBatch.objects.filter(
            status__in=(CompostBatch.Status.COLLECTING, CompostBatch.Status.PROCESSING),
        ).count(),
        'pending_sales_orders': SalesOrder.objects.filter(
            status=SalesOrder.Status.PENDING,
        ).count(),
        'unread_notification_count': request.user.notifications.filter(
            is_read=False,
        ).count(),
        'pickup_requests': pickup_requests,
        'tracking_pickups': pickup_requests.filter(
            status__in=(
                PickupRequest.Status.PENDING,
                PickupRequest.Status.APPROVED,
            ),
        ).order_by('pickup_date', 'created_at')[:6],
        'customers': (
            get_user_model().objects.filter(is_staff=False, is_superuser=False)
            .select_related('profile')
            .annotate(pickup_count=Count('pickup_requests'))
            .order_by('username')
        ),
        'categories': WasteCategory.objects.order_by('name'),
        'category_form': WasteCategoryForm(),
        'status_choices': (
            PickupRequest.Status.APPROVED,
            PickupRequest.Status.COMPLETED,
            PickupRequest.Status.REJECTED,
        ),
    }
    return render(request, 'waste_app/admin_dashboard.html', context)


@user_passes_test(staff_required, login_url='login')
@require_POST
def create_category(request):
    form = WasteCategoryForm(request.POST)
    if form.is_valid():
        category = form.save()
        messages.success(request, f'{category.name} was added.')
    else:
        messages.error(request, f'Category was not added: {form.errors.as_text()}')
    return redirect(f'{reverse("admin_dashboard")}#categories')


@user_passes_test(staff_required, login_url='login')
@require_POST
def update_category(request, category_id):
    category = get_object_or_404(WasteCategory, pk=category_id)
    form = WasteCategoryForm(request.POST, instance=category)
    if form.is_valid():
        category = form.save()
        messages.success(request, f'{category.name} was updated.')
    else:
        messages.error(request, f'Category was not updated: {form.errors.as_text()}')
    return redirect(f'{reverse("admin_dashboard")}#categories')


@user_passes_test(staff_required, login_url='login')
def dispatch_dashboard(request):
    routes = CollectionRoute.objects.select_related(
        'zone',
        'vehicle',
    ).prefetch_related(
        Prefetch(
            'stops',
            queryset=RouteStop.objects.select_related(
                'pickup__user',
                'pickup__category',
                'pickup__zone',
            ),
        ),
        Prefetch(
            'location_updates',
            queryset=LocationUpdate.objects.select_related('created_by'),
        ),
    )
    pickup_requests = PickupRequest.objects.select_related(
        'user',
        'category',
        'zone',
        'route_stop__route__zone',
        'route_stop__route__vehicle',
        'recycling_record',
    )
    context = {
        'vehicles': Vehicle.objects.all(),
        'vehicle_status_choices': Vehicle.Status.choices,
        'zones': CollectionZone.objects.all(),
        'routes': routes,
        'pickup_requests': pickup_requests,
        'tracking_pickups': pickup_requests.filter(
            status__in=(
                PickupRequest.Status.PENDING,
                PickupRequest.Status.APPROVED,
            ),
        ).order_by('pickup_date', 'created_at')[:6],
        'bulk_requests': pickup_requests.exclude(
            customer_type=PickupRequest.CustomerType.HOUSEHOLD,
        ),
        'recycling_records': RecyclingRecord.objects.select_related(
            'pickup__user',
            'pickup__category',
        ),
        'vehicle_form': VehicleForm(),
        'zone_form': CollectionZoneForm(),
        'route_form': CollectionRouteForm(),
        'route_stop_form': RouteStopForm(),
        'location_form': LocationUpdateForm(),
        'recycling_form': RecyclingRecordForm(),
        'unread_notification_count': request.user.notifications.filter(
            is_read=False,
        ).count(),
        'status_choices': (
            PickupRequest.Status.APPROVED,
            PickupRequest.Status.COMPLETED,
            PickupRequest.Status.REJECTED,
        ),
    }
    return render(request, 'waste_app/dispatch.html', context)


@user_passes_test(staff_required, login_url='login')
@require_POST
def create_vehicle(request):
    form = VehicleForm(request.POST)
    if form.is_valid():
        vehicle = form.save()
        messages.success(request, f'Vehicle {vehicle.vehicle_code} was registered.')
    else:
        messages.error(request, f'Vehicle was not registered: {form.errors.as_text()}')
    return redirect(f'{reverse("dispatch_dashboard")}#vehicles')


@user_passes_test(staff_required, login_url='login')
@require_POST
def update_vehicle_status(request, vehicle_id):
    vehicle = get_object_or_404(Vehicle, pk=vehicle_id)
    new_status = request.POST.get('status')
    active_routes = CollectionRoute.objects.filter(
        vehicle=vehicle,
        status=CollectionRoute.Status.ACTIVE,
    )
    if new_status not in Vehicle.Status.values:
        messages.error(request, 'Select a valid vehicle status.')
    elif new_status == Vehicle.Status.MAINTENANCE and active_routes.exists():
        messages.error(request, 'A vehicle on an active route cannot be sent to maintenance.')
    elif (
        new_status == Vehicle.Status.AVAILABLE
        and active_routes.exists()
    ):
        messages.error(request, 'Complete or cancel the active route before freeing this vehicle.')
    elif (
        new_status == Vehicle.Status.ON_ROUTE
        and not active_routes.exists()
    ):
        messages.error(request, 'Assign the vehicle to an active route before marking it on route.')
    else:
        vehicle.status = new_status
        vehicle.save(update_fields=['status'])
        messages.success(request, f'{vehicle.vehicle_code} is now {new_status.lower()}.')
    return redirect(f'{reverse("dispatch_dashboard")}#vehicles')


@user_passes_test(staff_required, login_url='login')
@require_POST
def create_zone(request):
    form = CollectionZoneForm(request.POST)
    if form.is_valid():
        zone = form.save()
        messages.success(request, f'Collection zone {zone.name} was added.')
    else:
        messages.error(request, f'Zone was not added: {form.errors.as_text()}')
    return redirect(f'{reverse("dispatch_dashboard")}#zones')


@user_passes_test(staff_required, login_url='login')
@require_POST
def update_zone(request, zone_id):
    zone = get_object_or_404(CollectionZone, pk=zone_id)
    form = CollectionZoneUpdateForm(request.POST, instance=zone)
    if form.is_valid():
        zone = form.save()
        messages.success(
            request,
            f'Collection zone {zone.name} was updated.',
        )
    else:
        messages.error(request, f'Zone was not updated: {form.errors.as_text()}')
    return redirect(f'{reverse("dispatch_dashboard")}#zones')


@user_passes_test(staff_required, login_url='login')
@require_POST
def create_route(request):
    form = CollectionRouteForm(request.POST)
    if form.is_valid():
        route = form.save()
        if route.status == CollectionRoute.Status.ACTIVE and route.vehicle_id:
            Vehicle.objects.filter(pk=route.vehicle_id).update(
                status=Vehicle.Status.ON_ROUTE,
            )
        messages.success(request, f'Route {route.name} was created.')
    else:
        messages.error(request, f'Route was not created: {form.errors.as_text()}')
    return redirect(f'{reverse("dispatch_dashboard")}#routes')


@user_passes_test(staff_required, login_url='login')
@require_POST
def assign_route_stop(request):
    pickup_id = request.POST.get('pickup')
    instance = None
    if pickup_id and pickup_id.isdigit():
        instance = RouteStop.objects.filter(pickup_id=pickup_id).first()
    form = RouteStopForm(request.POST, instance=instance)
    if not form.is_valid():
        messages.error(request, f'Stop was not assigned: {form.errors.as_text()}')
        return redirect(f'{reverse("dispatch_dashboard")}#routes')

    route = form.cleaned_data['route']
    pickup = form.cleaned_data['pickup']
    if pickup.status != PickupRequest.Status.APPROVED:
        messages.error(request, 'Approve the pickup request before adding it to a route.')
        return redirect(f'{reverse("dispatch_dashboard")}#routes')
    if route.vehicle is None or route.vehicle.status == Vehicle.Status.MAINTENANCE:
        messages.error(request, 'Assign an available vehicle to the route first.')
        return redirect(f'{reverse("dispatch_dashboard")}#routes')
    if pickup.zone_id and pickup.zone_id != route.zone_id:
        messages.error(request, 'The pickup zone must match the route zone.')
        return redirect(f'{reverse("dispatch_dashboard")}#routes')

    route_stops = route.stops.all()
    if instance and instance.route_id == route.pk:
        route_stops = route_stops.exclude(pk=instance.pk)
    assigned_weight = (
        route_stops.aggregate(total=Sum('pickup__estimated_weight_kg'))['total']
        or Decimal('0')
    )
    if assigned_weight + pickup.estimated_weight_kg > route.vehicle.capacity_kg:
        messages.error(
            request,
            f'The route would exceed {route.vehicle.vehicle_code} capacity '
            f'({route.vehicle.capacity_kg} kg).',
        )
        return redirect(f'{reverse("dispatch_dashboard")}#routes')

    stop = form.save()
    messages.success(
        request,
        f'Pickup #{pickup.pk} was assigned as stop {stop.stop_order} on {route.name}.',
    )
    return redirect(f'{reverse("dispatch_dashboard")}#routes')


@user_passes_test(staff_required, login_url='login')
@require_POST
def add_location_update(request):
    form = LocationUpdateForm(request.POST)
    if not form.is_valid():
        messages.error(request, f'Location was not updated: {form.errors.as_text()}')
        return redirect(f'{reverse("dispatch_dashboard")}#tracking')

    with transaction.atomic():
        route = get_object_or_404(
            CollectionRoute.objects.select_for_update().select_related('vehicle'),
            pk=form.cleaned_data['route'].pk,
        )
        route_status = form.cleaned_data['route_status']
        vehicle = route.vehicle
        if route_status == CollectionRoute.Status.ACTIVE and (
            vehicle is None or vehicle.status == Vehicle.Status.MAINTENANCE
        ):
            messages.error(request, 'An active route needs an available vehicle.')
            return redirect(f'{reverse("dispatch_dashboard")}#tracking')
        other_active_routes = CollectionRoute.objects.filter(
            vehicle=vehicle,
            status=CollectionRoute.Status.ACTIVE,
        ).exclude(pk=route.pk)
        if route_status == CollectionRoute.Status.ACTIVE and other_active_routes.exists():
            messages.error(request, 'This vehicle is already assigned to an active route.')
            return redirect(f'{reverse("dispatch_dashboard")}#tracking')

        update = form.save(commit=False)
        update.route = route
        update.created_by = request.user
        update.save()
        route.status = route_status
        route.current_checkpoint = update.checkpoint
        route.save(update_fields=['status', 'current_checkpoint'])

        if vehicle:
            vehicle.current_checkpoint = update.checkpoint
            vehicle.location_updated_at = update.created_at
            if update.latitude is not None and update.longitude is not None:
                vehicle.current_latitude = update.latitude
                vehicle.current_longitude = update.longitude
            if route_status == CollectionRoute.Status.ACTIVE:
                vehicle.status = Vehicle.Status.ON_ROUTE
            elif route_status in (
                CollectionRoute.Status.COMPLETED,
                CollectionRoute.Status.CANCELLED,
            ) and not other_active_routes.exists():
                vehicle.status = Vehicle.Status.AVAILABLE
            vehicle.save(update_fields=[
                'current_checkpoint',
                'location_updated_at',
                'current_latitude',
                'current_longitude',
                'status',
            ])

    messages.success(request, f'Route {route.name} tracking was updated.')
    return redirect(f'{reverse("dispatch_dashboard")}#tracking')


def _estimated_pickup_points(pickup):
    return int(
        (pickup.estimated_weight_kg * Decimal(pickup.category.points_per_kg))
        .quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    )


def _pickup_status_redirect(request):
    if request.POST.get('return_to') == 'dispatch':
        return f'{reverse("dispatch_dashboard")}#bulk-requests'
    return 'admin_dashboard'


@user_passes_test(staff_required, login_url='login')
@require_POST
def update_recycling_record(request, pickup_id):
    with transaction.atomic():
        pickup = get_object_or_404(
            PickupRequest.objects.select_for_update().select_related(
                'user',
                'category',
            ),
            pk=pickup_id,
        )
        already_awarded = pickup.points_awarded
        record, record_created = RecyclingRecord.objects.select_for_update().get_or_create(
            pickup=pickup,
            defaults={
                'classification': (
                    RecyclingRecord.Classification.RECYCLABLE
                    if already_awarded
                    else RecyclingRecord.Classification.UNCLASSIFIED
                ),
                'sorted_weight_kg': (
                    pickup.estimated_weight_kg if already_awarded else None
                ),
                'stage': (
                    RecyclingRecord.Stage.RECYCLED
                    if already_awarded
                    else RecyclingRecord.Stage.AWAITING_SORTING
                ),
                'eco_points_awarded': (
                    _estimated_pickup_points(pickup) if already_awarded else 0
                ),
            },
        )
        previous_stage = record.stage
        form = RecyclingRecordForm(request.POST, instance=record)
        if not form.is_valid():
            messages.error(
                request,
                f'Recycling record was not updated: {form.errors.as_text()}',
            )
            return redirect(f'{reverse("dispatch_dashboard")}#recycling')

        record = form.save(commit=False)
        record.updated_by = request.user
        new_points = record.calculate_eco_points()
        if already_awarded:
            point_delta = new_points - record.eco_points_awarded
            if point_delta:
                profile, _ = UserProfile.objects.select_for_update().get_or_create(
                    user=pickup.user,
                )
                UserProfile.objects.filter(pk=profile.pk).update(
                    eco_points=F('eco_points') + point_delta,
                )
            record.eco_points_awarded = new_points
        record.save()
        if previous_stage != record.stage:
            _create_notification(
                pickup.user,
                UserNotification.Category.STATUS,
                'Recycling progress updated',
                f'Pickup #{pickup.pk} moved to the {record.get_stage_display()} stage.',
                pickup=pickup,
            )

    messages.success(request, f'Recycling details for pickup #{pickup.pk} were updated.')
    return redirect(f'{reverse("dispatch_dashboard")}#recycling')


@user_passes_test(staff_required, login_url='login')
@require_POST
def update_pickup_status(request, pickup_id):
    new_status = request.POST.get('status')
    allowed_statuses = {
        PickupRequest.Status.APPROVED,
        PickupRequest.Status.COMPLETED,
        PickupRequest.Status.REJECTED,
    }
    if new_status not in allowed_statuses:
        messages.error(request, 'Select a valid pickup status.')
        return redirect(_pickup_status_redirect(request))

    with transaction.atomic():
        pickup = get_object_or_404(
            PickupRequest.objects.select_for_update().select_related('category', 'user'),
            pk=pickup_id,
        )
        previous_status = pickup.status
        pickup.status = new_status

        if new_status == PickupRequest.Status.COMPLETED:
            if previous_status != PickupRequest.Status.COMPLETED or pickup.completed_at is None:
                pickup.completed_at = timezone.now()
            recyclable = pickup.category.is_recyclable
            record, record_created = RecyclingRecord.objects.get_or_create(
                pickup=pickup,
                defaults={
                    'classification': (
                        RecyclingRecord.Classification.RECYCLABLE
                        if recyclable or pickup.points_awarded
                        else RecyclingRecord.Classification.NON_RECYCLABLE
                    ),
                    'sorted_weight_kg': pickup.estimated_weight_kg,
                    'stage': (
                        RecyclingRecord.Stage.RECYCLED
                        if recyclable or pickup.points_awarded
                        else RecyclingRecord.Stage.DISPOSED
                    ),
                },
            )
            if not pickup.points_awarded:
                profile, _ = UserProfile.objects.select_for_update().get_or_create(
                    user=pickup.user,
                )
                earned_points = record.calculate_eco_points()
                UserProfile.objects.filter(pk=profile.pk).update(
                    eco_points=F('eco_points') + earned_points,
                )
                pickup.points_awarded = True
                record.eco_points_awarded = earned_points
                record.save(update_fields=['eco_points_awarded'])
            elif record_created:
                record.eco_points_awarded = _estimated_pickup_points(pickup)
                record.save(update_fields=['eco_points_awarded'])
            stop = RouteStop.objects.filter(pickup=pickup).select_related('route__vehicle').first()
            if stop:
                stop.status = RouteStop.Status.COLLECTED
                stop.save(update_fields=['status'])
        elif previous_status == PickupRequest.Status.COMPLETED:
            pickup.completed_at = None
        if new_status == PickupRequest.Status.REJECTED:
            stop = RouteStop.objects.filter(pickup=pickup).first()
            if stop:
                stop.status = RouteStop.Status.SKIPPED
                stop.save(update_fields=['status'])
        if new_status in (
            PickupRequest.Status.COMPLETED,
            PickupRequest.Status.REJECTED,
        ):
            stop = RouteStop.objects.filter(pickup=pickup).first()
            if stop:
                _close_route_if_finished(stop.route_id)

        pickup.save(update_fields=['status', 'completed_at', 'points_awarded'])
        if previous_status != new_status:
            category = (
                UserNotification.Category.COLLECTION
                if new_status == PickupRequest.Status.APPROVED
                else UserNotification.Category.STATUS
            )
            _create_notification(
                pickup.user,
                category,
                f'Pickup {new_status.lower()}',
                f'Pickup request #{pickup.pk} is now {new_status.lower()}.',
                pickup=pickup,
            )

    messages.success(request, f'Pickup request #{pickup.pk} marked {new_status.lower()}.')
    return redirect(_pickup_status_redirect(request))


@login_required(login_url='login')
def notifications(request):
    user_notifications = request.user.notifications.select_related(
        'pickup',
        'order__product',
    )
    return render(
        request,
        'waste_app/notifications.html',
        {
            'notifications': user_notifications,
            'unread_notification_count': user_notifications.filter(is_read=False).count(),
        },
    )


@login_required(login_url='login')
@require_POST
def mark_notification_read(request, notification_id):
    notification = get_object_or_404(
        UserNotification.objects.filter(recipient=request.user),
        pk=notification_id,
    )
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=['is_read'])
    return redirect('notifications')


@login_required(login_url='login')
@require_POST
def mark_all_notifications_read(request):
    request.user.notifications.filter(is_read=False).update(is_read=True)
    messages.success(request, 'All notifications have been marked as read.')
    return redirect('notifications')


@login_required(login_url='login')
def marketplace(request):
    form = SalesOrderForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        quantity = form.cleaned_data['quantity_kg']
        with transaction.atomic():
            product = get_object_or_404(
                CompostProduct.objects.select_for_update(),
                pk=form.cleaned_data['product'].pk,
                is_active=True,
            )
            if product.stock_kg < quantity:
                messages.error(
                    request,
                    f'Only {product.stock_kg} kg of {product.name} is currently available.',
                )
                return redirect('marketplace')
            price = product.price_per_kg
            total = (price * quantity).quantize(
                Decimal('0.01'),
                rounding=ROUND_HALF_UP,
            )
            product.stock_kg -= quantity
            product.save(update_fields=['stock_kg', 'updated_at'])
            order = SalesOrder.objects.create(
                user=request.user,
                product=product,
                quantity_kg=quantity,
                price_per_kg=price,
                total_amount=total,
                status=SalesOrder.Status.PENDING,
                stock_deducted=True,
            )
            _create_notification(
                request.user,
                UserNotification.Category.ORDER,
                'Order received',
                f'Order #{order.pk} for {quantity} kg of {product.name} is awaiting approval.',
                order=order,
            )
            for staff_user in get_user_model().objects.filter(
                is_active=True,
                is_staff=True,
            ):
                _create_notification(
                    staff_user,
                    UserNotification.Category.ORDER,
                    'New compost product order',
                    f'{request.user.get_username()} ordered {quantity} kg of {product.name}.',
                    order=order,
                )
        messages.success(request, 'Your order was placed and inventory was reserved.')
        return redirect('marketplace')

    products = CompostProduct.objects.filter(
        is_active=True,
        stock_kg__gt=0,
    ).select_related('compost_batch')
    return render(
        request,
        'waste_app/marketplace.html',
        {
            'form': form,
            'products': products,
            'orders': request.user.compost_orders.select_related('product'),
            'unread_notification_count': request.user.notifications.filter(
                is_read=False,
            ).count(),
        },
    )


@login_required(login_url='login')
@require_POST
def cancel_sales_order(request, order_id):
    with transaction.atomic():
        order = get_object_or_404(
            SalesOrder.objects.select_for_update().select_related('product'),
            pk=order_id,
            user=request.user,
        )
        if order.status not in (SalesOrder.Status.PENDING, SalesOrder.Status.APPROVED):
            messages.error(request, 'Only pending or approved orders can be cancelled.')
        else:
            if order.stock_deducted:
                product = CompostProduct.objects.select_for_update().get(
                    pk=order.product_id,
                )
                product.stock_kg += order.quantity_kg
                product.save(update_fields=['stock_kg', 'updated_at'])
                order.stock_deducted = False
            order.status = SalesOrder.Status.CANCELLED
            order.save(update_fields=['status', 'stock_deducted', 'updated_at'])
            _create_notification(
                request.user,
                UserNotification.Category.ORDER,
                'Order cancelled',
                f'Order #{order.pk} has been cancelled and its inventory released.',
                order=order,
            )
            messages.success(request, f'Order #{order.pk} was cancelled.')
    return redirect('marketplace')


@user_passes_test(staff_required, login_url='login')
def compost_management(request):
    batches = list(CompostBatch.objects.prefetch_related(
        'source_pickups__user',
    ).select_related('created_by'))
    for batch in batches:
        batch.edit_form = CompostBatchForm(instance=batch)
    return render(
        request,
        'waste_app/compost_management.html',
        {
            'batch_form': CompostBatchForm(),
            'batches': batches,
            'unread_notification_count': request.user.notifications.filter(
                is_read=False,
            ).count(),
        },
    )


def _notify_compost_ready(batch):
    for pickup in batch.source_pickups.select_related('user'):
        _create_notification(
            pickup.user,
            UserNotification.Category.STATUS,
            'Compost batch ready',
            f'Organic waste from pickup #{pickup.pk} contributed to compost batch '
            f'{batch.batch_code}, now ready for use.',
            pickup=pickup,
        )


@user_passes_test(staff_required, login_url='login')
@require_POST
def create_compost_batch(request):
    form = CompostBatchForm(request.POST)
    if not form.is_valid():
        messages.error(request, f'Compost batch was not created: {form.errors.as_text()}')
        return redirect(f'{reverse("compost_management")}#batches')
    with transaction.atomic():
        batch = form.save(commit=False)
        batch.created_by = request.user
        if batch.status == CompostBatch.Status.READY:
            batch.ready_at = timezone.now()
        batch.save()
        form.save_m2m()
        if batch.status == CompostBatch.Status.READY:
            _notify_compost_ready(batch)
    messages.success(request, f'Compost batch {batch.batch_code} was created.')
    return redirect(f'{reverse("compost_management")}#batches')


@user_passes_test(staff_required, login_url='login')
@require_POST
def update_compost_batch(request, batch_id):
    with transaction.atomic():
        batch = get_object_or_404(
            CompostBatch.objects.select_for_update(),
            pk=batch_id,
        )
        previous_status = batch.status
        form = CompostBatchForm(request.POST, instance=batch)
        if not form.is_valid():
            messages.error(request, f'Compost batch was not updated: {form.errors.as_text()}')
            return redirect(f'{reverse("compost_management")}#batches')
        batch = form.save(commit=False)
        if batch.status == CompostBatch.Status.READY:
            batch.ready_at = batch.ready_at or timezone.now()
        else:
            batch.ready_at = None
        batch.save()
        form.save_m2m()
        if (
            previous_status != CompostBatch.Status.READY
            and batch.status == CompostBatch.Status.READY
        ):
            _notify_compost_ready(batch)
    messages.success(request, f'Compost batch {batch.batch_code} was updated.')
    return redirect(f'{reverse("compost_management")}#batches')


@user_passes_test(staff_required, login_url='login')
def sales_management(request):
    products = list(CompostProduct.objects.select_related('compost_batch'))
    for product in products:
        product.edit_form = CompostProductForm(instance=product)
    orders = list(SalesOrder.objects.select_related('user', 'product'))
    for order in orders:
        if order.status == SalesOrder.Status.PENDING:
            allowed_statuses = (
                SalesOrder.Status.APPROVED,
                SalesOrder.Status.REJECTED,
            )
        elif order.status == SalesOrder.Status.APPROVED:
            allowed_statuses = (
                SalesOrder.Status.FULFILLED,
                SalesOrder.Status.REJECTED,
            )
        else:
            allowed_statuses = ()
        order.available_status_choices = tuple(
            choice for choice in SalesOrder.Status.choices
            if choice[0] in allowed_statuses
        )
    return render(
        request,
        'waste_app/sales_management.html',
        {
            'product_form': CompostProductForm(),
            'products': products,
            'orders': orders,
            'unread_notification_count': request.user.notifications.filter(
                is_read=False,
            ).count(),
        },
    )


@user_passes_test(staff_required, login_url='login')
@require_POST
def create_compost_product(request):
    form = CompostProductForm(request.POST)
    if form.is_valid():
        product = form.save()
        messages.success(request, f'{product.name} was added to the product catalog.')
    else:
        messages.error(request, f'Product was not saved: {form.errors.as_text()}')
    return redirect(f'{reverse("sales_management")}#products')


@user_passes_test(staff_required, login_url='login')
@require_POST
def update_compost_product(request, product_id):
    product = get_object_or_404(CompostProduct, pk=product_id)
    form = CompostProductForm(request.POST, instance=product)
    if form.is_valid():
        product = form.save()
        messages.success(request, f'{product.name} was updated.')
    else:
        messages.error(request, f'Product was not updated: {form.errors.as_text()}')
    return redirect(f'{reverse("sales_management")}#products')


@user_passes_test(staff_required, login_url='login')
@require_POST
def update_sales_order(request, order_id):
    new_status = request.POST.get('status')
    allowed_statuses = {
        SalesOrder.Status.APPROVED,
        SalesOrder.Status.FULFILLED,
        SalesOrder.Status.REJECTED,
    }
    if new_status not in allowed_statuses:
        messages.error(request, 'Choose a valid order status.')
        return redirect(f'{reverse("sales_management")}#orders')

    with transaction.atomic():
        order = get_object_or_404(
            SalesOrder.objects.select_for_update().select_related('product', 'user'),
            pk=order_id,
        )
        transition_allowed = (
            (new_status == SalesOrder.Status.APPROVED
             and order.status == SalesOrder.Status.PENDING)
            or (new_status == SalesOrder.Status.FULFILLED
                and order.status == SalesOrder.Status.APPROVED)
            or (new_status == SalesOrder.Status.REJECTED
                and order.status in (
                    SalesOrder.Status.PENDING,
                    SalesOrder.Status.APPROVED,
                ))
        )
        if not transition_allowed:
            messages.error(request, 'That order status transition is not allowed.')
            return redirect(f'{reverse("sales_management")}#orders')

        if new_status == SalesOrder.Status.REJECTED and order.stock_deducted:
            product = CompostProduct.objects.select_for_update().get(
                pk=order.product_id,
            )
            product.stock_kg += order.quantity_kg
            product.save(update_fields=['stock_kg', 'updated_at'])
            order.stock_deducted = False
        order.status = new_status
        order.save(update_fields=['status', 'stock_deducted', 'updated_at'])
        _create_notification(
            order.user,
            UserNotification.Category.ORDER,
            'Order status updated',
            f'Order #{order.pk} for {order.product.name} is now {new_status.lower()}.',
            order=order,
        )
    messages.success(request, f'Order #{order.pk} marked {new_status.lower()}.')
    return redirect(f'{reverse("sales_management")}#orders')


@user_passes_test(staff_required, login_url='login')
def reports(request):
    completed_pickups = PickupRequest.objects.filter(
        status=PickupRequest.Status.COMPLETED,
    )
    recycled_records = RecyclingRecord.objects.filter(
        classification=RecyclingRecord.Classification.RECYCLABLE,
        stage=RecyclingRecord.Stage.RECYCLED,
    )
    compost_batches = CompostBatch.objects.all()
    fulfilled_orders = SalesOrder.objects.filter(
        status=SalesOrder.Status.FULFILLED,
    )
    return render(
        request,
        'waste_app/reports.html',
        {
            'completed_pickup_count': completed_pickups.count(),
            'collected_weight': (
                completed_pickups.aggregate(total=Sum('estimated_weight_kg'))['total']
                or Decimal('0')
            ),
            'recycled_weight': (
                recycled_records.aggregate(total=Sum('sorted_weight_kg'))['total']
                or Decimal('0')
            ),
            'compost_input_weight': (
                compost_batches.aggregate(total=Sum('input_weight_kg'))['total']
                or Decimal('0')
            ),
            'compost_yield_weight': (
                compost_batches.filter(status=CompostBatch.Status.READY)
                .aggregate(total=Sum('yield_kg'))['total']
                or Decimal('0')
            ),
            'sales_revenue': (
                fulfilled_orders.aggregate(total=Sum('total_amount'))['total']
                or Decimal('0')
            ),
            'pending_sales_orders': SalesOrder.objects.filter(
                status=SalesOrder.Status.PENDING,
            ).count(),
            'category_breakdown': completed_pickups.values(
                'category__name',
            ).annotate(
                request_count=Count('pk'),
                collected_kg=Sum('estimated_weight_kg'),
            ).order_by('category__name'),
            'collection_status_breakdown': PickupRequest.objects.values(
                'status',
            ).annotate(request_count=Count('pk')).order_by('status'),
            'recycling_stage_breakdown': RecyclingRecord.objects.values(
                'classification',
                'stage',
            ).annotate(
                record_count=Count('pk'),
                sorted_kg=Sum('sorted_weight_kg'),
            ).order_by('classification', 'stage'),
            'unread_notification_count': request.user.notifications.filter(
                is_read=False,
            ).count(),
        },
    )


@user_passes_test(staff_required, login_url='login')
@require_POST
def update_customer_access(request, user_id):
    customer = get_object_or_404(
        get_user_model().objects.filter(is_staff=False, is_superuser=False),
        pk=user_id,
    )
    active_value = request.POST.get('is_active')
    if active_value not in ('true', 'false'):
        messages.error(request, 'Choose a valid customer account state.')
    else:
        customer.is_active = active_value == 'true'
        customer.save(update_fields=['is_active'])
        state = 'activated' if customer.is_active else 'deactivated'
        messages.success(request, f'{customer.get_username()} was {state}.')
    return redirect(f'{reverse("admin_dashboard")}#customers')
