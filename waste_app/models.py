from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    phone = models.CharField(max_length=32, blank=True, default='')
    address = models.TextField(blank=True, default='')
    eco_points = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f'Profile for {self.user}'


class CollectionZone(models.Model):
    name = models.CharField(max_length=100, unique=True)
    area_description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name


class WasteCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    points_per_kg = models.PositiveIntegerField(default=10)
    is_recyclable = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Vehicle(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = 'Available', 'Available'
        ON_ROUTE = 'On Route', 'On Route'
        MAINTENANCE = 'Maintenance', 'Maintenance'

    vehicle_code = models.CharField(max_length=32, unique=True)
    capacity_kg = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    operator_name = models.CharField(max_length=150)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.AVAILABLE,
    )
    current_latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        blank=True,
        null=True,
    )
    current_longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        blank=True,
        null=True,
    )
    current_checkpoint = models.CharField(max_length=255, blank=True)
    location_updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ('vehicle_code',)

    def __str__(self):
        return f'{self.vehicle_code} — {self.operator_name}'


class PickupRequest(models.Model):
    class CustomerType(models.TextChoices):
        HOUSEHOLD = 'Household', 'Household'
        HOTEL = 'Hotel', 'Hotel'
        INDUSTRIAL = 'Industrial', 'Industrial'
        BULK = 'Bulk', 'Bulk'

    class CustomerTier(models.TextChoices):
        STANDARD = 'Standard', 'Standard'
        COMMERCIAL = 'Commercial', 'Commercial'
        ENTERPRISE = 'Enterprise', 'Enterprise'

    class Status(models.TextChoices):
        PENDING = 'Pending', 'Pending'
        APPROVED = 'Approved', 'Approved'
        COMPLETED = 'Completed', 'Completed'
        REJECTED = 'Rejected', 'Rejected'
        CANCELLED = 'Cancelled', 'Cancelled'

    class TimeSlot(models.TextChoices):
        MORNING = 'Morning 8AM-12PM', 'Morning 8AM-12PM'
        AFTERNOON = 'Afternoon 1PM-5PM', 'Afternoon 1PM-5PM'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pickup_requests',
    )
    category = models.ForeignKey(
        WasteCategory,
        on_delete=models.PROTECT,
        related_name='pickup_requests',
    )
    zone = models.ForeignKey(
        CollectionZone,
        on_delete=models.SET_NULL,
        related_name='pickup_requests',
        blank=True,
        null=True,
    )
    pickup_address = models.TextField()
    pickup_date = models.DateField()
    time_slot = models.CharField(
        max_length=32,
        choices=TimeSlot.choices,
        default=TimeSlot.MORNING,
    )
    estimated_weight_kg = models.DecimalField(max_digits=7, decimal_places=2)
    customer_type = models.CharField(
        max_length=16,
        choices=CustomerType.choices,
        default=CustomerType.HOUSEHOLD,
    )
    customer_tier = models.CharField(
        max_length=16,
        choices=CustomerTier.choices,
        default=CustomerTier.STANDARD,
    )
    bulk_weight_kg = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    special_handling_notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    points_awarded = models.BooleanField(default=False)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.category} pickup for {self.user} on {self.pickup_date}'


class CollectionRoute(models.Model):
    class Status(models.TextChoices):
        PLANNED = 'Planned', 'Planned'
        ACTIVE = 'Active', 'Active'
        COMPLETED = 'Completed', 'Completed'
        CANCELLED = 'Cancelled', 'Cancelled'

    name = models.CharField(max_length=120)
    zone = models.ForeignKey(
        CollectionZone,
        on_delete=models.PROTECT,
        related_name='routes',
    )
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.SET_NULL,
        related_name='routes',
        blank=True,
        null=True,
    )
    scheduled_date = models.DateField()
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PLANNED,
    )
    current_checkpoint = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('scheduled_date', 'name')

    def clean(self):
        if self.status == self.Status.ACTIVE and self.vehicle_id is None:
            from django.core.exceptions import ValidationError

            raise ValidationError({'vehicle': 'An active route must have a vehicle.'})
        if (
            self.status == self.Status.ACTIVE
            and self.vehicle_id
            and self.vehicle.status == Vehicle.Status.MAINTENANCE
        ):
            from django.core.exceptions import ValidationError

            raise ValidationError({'vehicle': 'A vehicle in maintenance cannot run a route.'})

    def __str__(self):
        return f'{self.name} — {self.scheduled_date}'


class RouteStop(models.Model):
    class Status(models.TextChoices):
        PLANNED = 'Planned', 'Planned'
        EN_ROUTE = 'En Route', 'En Route'
        COLLECTED = 'Collected', 'Collected'
        SKIPPED = 'Skipped', 'Skipped'

    route = models.ForeignKey(
        CollectionRoute,
        on_delete=models.CASCADE,
        related_name='stops',
    )
    pickup = models.OneToOneField(
        PickupRequest,
        on_delete=models.CASCADE,
        related_name='route_stop',
    )
    stop_order = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PLANNED,
    )

    class Meta:
        ordering = ('stop_order',)
        constraints = [
            models.UniqueConstraint(
                fields=('route', 'stop_order'),
                name='unique_collection_route_stop_order',
            ),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.route_id and self.pickup_id:
            if self.route.scheduled_date != self.pickup.pickup_date:
                raise ValidationError({
                    'route': 'The route date must match the pickup date.',
                })
            if self.route.status in (
                CollectionRoute.Status.COMPLETED,
                CollectionRoute.Status.CANCELLED,
            ):
                raise ValidationError({'route': 'A closed route cannot accept new stops.'})

    @property
    def estimated_arrival(self):
        if (
            self.pickup.status not in (
                PickupRequest.Status.PENDING,
                PickupRequest.Status.APPROVED,
            )
            or self.status in (self.Status.COLLECTED, self.Status.SKIPPED)
            or self.route.status in (
                CollectionRoute.Status.COMPLETED,
                CollectionRoute.Status.CANCELLED,
            )
        ):
            return None

        slot_start = (
            time(hour=8)
            if self.pickup.time_slot == PickupRequest.TimeSlot.MORNING
            else time(hour=13)
        )
        scheduled_start = timezone.make_aware(
            datetime.combine(self.route.scheduled_date, slot_start),
            timezone.get_current_timezone(),
        )
        return scheduled_start + timedelta(minutes=30 * (self.stop_order - 1))

    def __str__(self):
        return f'{self.route} — stop {self.stop_order}'


class LocationUpdate(models.Model):
    route = models.ForeignKey(
        CollectionRoute,
        on_delete=models.CASCADE,
        related_name='location_updates',
    )
    checkpoint = models.CharField(max_length=255)
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        blank=True,
        null=True,
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        blank=True,
        null=True,
    )
    route_status = models.CharField(
        max_length=16,
        choices=CollectionRoute.Status.choices,
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='route_location_updates',
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)

    def clean(self):
        from django.core.exceptions import ValidationError

        if (self.latitude is None) != (self.longitude is None):
            raise ValidationError('Enter both coordinates or leave both blank.')
        if self.latitude is not None and not Decimal('-90') <= self.latitude <= Decimal('90'):
            raise ValidationError({'latitude': 'Latitude must be between -90 and 90.'})
        if self.longitude is not None and not Decimal('-180') <= self.longitude <= Decimal('180'):
            raise ValidationError({'longitude': 'Longitude must be between -180 and 180.'})

    def __str__(self):
        return f'{self.route}: {self.checkpoint} ({self.created_at:%Y-%m-%d %H:%M})'


class RecyclingRecord(models.Model):
    class Classification(models.TextChoices):
        UNCLASSIFIED = 'Unclassified', 'Unclassified'
        RECYCLABLE = 'Recyclable', 'Recyclable'
        NON_RECYCLABLE = 'Non-recyclable', 'Non-recyclable'

    class Stage(models.TextChoices):
        AWAITING_SORTING = 'Awaiting Sorting', 'Awaiting Sorting'
        SORTED = 'Sorted', 'Sorted'
        PROCESSING = 'Processing', 'Processing'
        RECYCLED = 'Recycled', 'Recycled'
        DISPOSED = 'Disposed', 'Disposed'

    pickup = models.OneToOneField(
        PickupRequest,
        on_delete=models.CASCADE,
        related_name='recycling_record',
    )
    classification = models.CharField(
        max_length=20,
        choices=Classification.choices,
        default=Classification.UNCLASSIFIED,
    )
    sorted_weight_kg = models.DecimalField(
        max_digits=9,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal('0'))],
    )
    stage = models.CharField(
        max_length=20,
        choices=Stage.choices,
        default=Stage.AWAITING_SORTING,
    )
    notes = models.TextField(blank=True)
    eco_points_awarded = models.PositiveIntegerField(default=0)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='recycling_record_updates',
        blank=True,
        null=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-updated_at',)

    def calculate_eco_points(self):
        if (
            self.classification != self.Classification.RECYCLABLE
            or self.stage != self.Stage.RECYCLED
            or self.sorted_weight_kg is None
        ):
            return 0
        return int(
            (self.sorted_weight_kg * Decimal(self.pickup.category.points_per_kg))
            .quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        )

    def __str__(self):
        return f'Recycling record for pickup #{self.pickup_id}'


class CompostBatch(models.Model):
    class Status(models.TextChoices):
        COLLECTING = 'Collecting', 'Collecting'
        PROCESSING = 'Processing', 'Processing'
        READY = 'Ready', 'Ready'
        REJECTED = 'Rejected', 'Rejected'

    batch_code = models.CharField(max_length=40, unique=True)
    source_pickups = models.ManyToManyField(
        PickupRequest,
        related_name='compost_batches',
        blank=True,
    )
    input_weight_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    yield_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal('0'))],
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.COLLECTING,
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='compost_batches_created',
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    ready_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ('-created_at',)

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.yield_kg is not None and self.yield_kg > self.input_weight_kg:
            raise ValidationError({'yield_kg': 'Compost yield cannot exceed the input weight.'})
        if self.status == self.Status.READY and self.yield_kg is None:
            raise ValidationError({'yield_kg': 'Enter the produced compost weight before marking a batch ready.'})

    def __str__(self):
        return self.batch_code


class CompostProduct(models.Model):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    compost_batch = models.ForeignKey(
        CompostBatch,
        on_delete=models.SET_NULL,
        related_name='products',
        blank=True,
        null=True,
    )
    price_per_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))],
    )
    stock_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))],
        default=Decimal('0'),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name


class SalesOrder(models.Model):
    class Status(models.TextChoices):
        PENDING = 'Pending', 'Pending'
        APPROVED = 'Approved', 'Approved'
        FULFILLED = 'Fulfilled', 'Fulfilled'
        REJECTED = 'Rejected', 'Rejected'
        CANCELLED = 'Cancelled', 'Cancelled'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='compost_orders',
    )
    product = models.ForeignKey(
        CompostProduct,
        on_delete=models.PROTECT,
        related_name='orders',
    )
    quantity_kg = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    price_per_kg = models.DecimalField(max_digits=10, decimal_places=2)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    stock_deducted = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f'Order #{self.pk} — {self.product.name}'


class UserNotification(models.Model):
    class Category(models.TextChoices):
        SCHEDULE = 'Schedule', 'Schedule Alert'
        COLLECTION = 'Collection', 'Collection Alert'
        STATUS = 'Status', 'Status Change'
        ORDER = 'Order', 'Order Update'

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    category = models.CharField(max_length=16, choices=Category.choices)
    title = models.CharField(max_length=150)
    message = models.TextField()
    pickup = models.ForeignKey(
        PickupRequest,
        on_delete=models.SET_NULL,
        related_name='notifications',
        blank=True,
        null=True,
    )
    order = models.ForeignKey(
        SalesOrder,
        on_delete=models.SET_NULL,
        related_name='notifications',
        blank=True,
        null=True,
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('is_read', '-created_at')

    def __str__(self):
        return f'{self.title} — {self.recipient}'
