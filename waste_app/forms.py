from django import forms
from django.contrib.auth import authenticate, get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

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
    Vehicle,
    WasteCategory,
)


class RegistrationForm(forms.Form):
    fullName = forms.CharField(max_length=150)
    phone = forms.CharField(max_length=32)
    email = forms.EmailField(max_length=150)
    address = forms.CharField(max_length=500)
    password = forms.CharField(widget=forms.PasswordInput)
    confirmPassword = forms.CharField(widget=forms.PasswordInput)
    terms = forms.BooleanField(required=True)

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        user_model = get_user_model()
        if user_model.objects.filter(email__iexact=email).exists():
            raise ValidationError('An account with this email already exists.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirmPassword')
        if password and confirm_password and password != confirm_password:
            self.add_error('confirmPassword', 'The passwords do not match.')
        if password:
            full_name = cleaned_data.get('fullName', '').strip().split(maxsplit=1)
            first_name = full_name[0] if full_name else ''
            last_name = full_name[1] if len(full_name) > 1 else ''
            user_model = get_user_model()
            candidate = user_model(
                username=cleaned_data.get('email', ''),
                email=cleaned_data.get('email', ''),
                first_name=first_name,
                last_name=last_name,
            )
            try:
                password_validation.validate_password(password, candidate)
            except ValidationError as error:
                self.add_error('password', error)
        return cleaned_data

    def save(self):
        user_model = get_user_model()
        full_name = self.cleaned_data['fullName'].strip().split(maxsplit=1)
        first_name = full_name[0]
        last_name = full_name[1] if len(full_name) > 1 else ''
        with transaction.atomic():
            user = user_model.objects.create_user(
                username=self.cleaned_data['email'],
                email=self.cleaned_data['email'],
                first_name=first_name,
                last_name=last_name,
                password=self.cleaned_data['password'],
            )
            UserProfile.objects.create(
                user=user,
                phone=self.cleaned_data['phone'],
                address=self.cleaned_data['address'],
            )
        return user


class EmailAuthenticationForm(forms.Form):
    email = forms.CharField(
        label='Email or username',
        max_length=254,
        strip=True,
    )
    password = forms.CharField(widget=forms.PasswordInput)
    remember = forms.BooleanField(required=False)

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        identifier = cleaned_data.get('email')
        password = cleaned_data.get('password')
        if identifier and password:
            user_model = get_user_model()
            if '@' in identifier:
                user = user_model.objects.filter(
                    email__iexact=identifier,
                ).first()
                if user is None:
                    user = user_model.objects.filter(
                        username__iexact=identifier,
                    ).first()
            else:
                user = user_model.objects.filter(
                    username__iexact=identifier,
                ).first()
                if user is None:
                    user = user_model.objects.filter(
                        email__iexact=identifier,
                    ).first()
            if user is not None:
                self.user = authenticate(
                    self.request,
                    username=user.get_username(),
                    password=password,
                )
            if self.user is None:
                raise ValidationError('Invalid email or password.')
        return cleaned_data

    def get_user(self):
        return self.user


class PickupRequestForm(forms.Form):
    category = forms.ModelChoiceField(queryset=WasteCategory.objects.order_by('name'))
    zone = forms.ModelChoiceField(
        queryset=CollectionZone.objects.filter(is_active=True).order_by('name'),
        required=False,
    )
    weight = forms.DecimalField(
        min_value=0.01,
        max_digits=7,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={'min': '0.01', 'step': '0.01'}),
    )
    bulk_weight = forms.DecimalField(
        min_value=0.01,
        max_digits=7,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={'min': '0.01', 'step': '0.01'}),
    )
    customer_type = forms.ChoiceField(
        choices=PickupRequest.CustomerType.choices,
        required=False,
    )
    customer_tier = forms.ChoiceField(
        choices=PickupRequest.CustomerTier.choices,
        required=False,
    )
    special_handling_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 2, 'maxlength': 2000}),
    )
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    timeSlot = forms.ChoiceField(choices=PickupRequest.TimeSlot.choices)
    address = forms.CharField(max_length=500)

    def clean(self):
        cleaned_data = super().clean()
        customer_type = (
            cleaned_data.get('customer_type')
            or PickupRequest.CustomerType.HOUSEHOLD
        )
        if customer_type == PickupRequest.CustomerType.HOUSEHOLD:
            if cleaned_data.get('weight') is None:
                self.add_error('weight', 'Enter the estimated pickup weight.')
        elif cleaned_data.get('bulk_weight') is None:
            self.add_error('bulk_weight', 'Enter the bulk waste weight.')
        return cleaned_data

    def save(self, user):
        customer_type = (
            self.cleaned_data['customer_type']
            or PickupRequest.CustomerType.HOUSEHOLD
        )
        weight = (
            self.cleaned_data['bulk_weight']
            if customer_type != PickupRequest.CustomerType.HOUSEHOLD
            else self.cleaned_data['weight']
        )
        return PickupRequest.objects.create(
            user=user,
            category=self.cleaned_data['category'],
            zone=self.cleaned_data['zone'],
            estimated_weight_kg=weight,
            customer_type=customer_type,
            customer_tier=(
                self.cleaned_data['customer_tier']
                or PickupRequest.CustomerTier.STANDARD
            ),
            bulk_weight_kg=(
                self.cleaned_data['bulk_weight']
                if customer_type != PickupRequest.CustomerType.HOUSEHOLD
                else None
            ),
            special_handling_notes=self.cleaned_data['special_handling_notes'],
            pickup_date=self.cleaned_data['date'],
            time_slot=self.cleaned_data['timeSlot'],
            pickup_address=self.cleaned_data['address'],
        )


class ProfileUpdateForm(forms.Form):
    full_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'w-full rounded-md border border-light-outline-variant bg-crisp-white px-gutter-md py-gutter-sm'}),
    )
    phone = forms.CharField(
        max_length=32,
        widget=forms.TextInput(attrs={'class': 'w-full rounded-md border border-light-outline-variant bg-crisp-white px-gutter-md py-gutter-sm'}),
    )
    address = forms.CharField(
        max_length=500,
        widget=forms.Textarea(
            attrs={
                'class': 'w-full rounded-md border border-light-outline-variant bg-crisp-white px-gutter-md py-gutter-sm',
                'rows': 3,
            },
        ),
    )

    def save(self, user, profile):
        names = self.cleaned_data['full_name'].split(maxsplit=1)
        user.first_name = names[0]
        user.last_name = names[1] if len(names) > 1 else ''
        profile.phone = self.cleaned_data['phone']
        profile.address = self.cleaned_data['address']
        with transaction.atomic():
            user.save(update_fields=['first_name', 'last_name'])
            profile.save(update_fields=['phone', 'address'])
        return profile


class PickupStatusFilterForm(forms.Form):
    status = forms.ChoiceField(
        required=False,
        choices=(('', 'All statuses'), *PickupRequest.Status.choices),
    )


class WasteCategoryForm(forms.ModelForm):
    class Meta:
        model = WasteCategory
        fields = ('name', 'description', 'points_per_kg', 'is_recyclable')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full rounded-md border border-light-outline-variant px-gutter-md py-gutter-sm'}),
            'description': forms.Textarea(attrs={'class': 'w-full rounded-md border border-light-outline-variant px-gutter-md py-gutter-sm', 'rows': 2}),
            'points_per_kg': forms.NumberInput(attrs={'class': 'w-full rounded-md border border-light-outline-variant px-gutter-md py-gutter-sm', 'min': '0'}),
        }


class VehicleForm(forms.ModelForm):
    capacity_kg = forms.DecimalField(
        min_value=0.01,
        max_digits=9,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'min': '0.01', 'step': '0.01'}),
    )

    class Meta:
        model = Vehicle
        fields = ('vehicle_code', 'capacity_kg', 'operator_name', 'status')

    def clean_status(self):
        status = self.cleaned_data['status']
        if self.instance._state.adding and status == Vehicle.Status.ON_ROUTE:
            raise ValidationError('Register a vehicle as available before dispatching it.')
        return status


class CollectionZoneForm(forms.ModelForm):
    class Meta:
        model = CollectionZone
        fields = ('name', 'area_description')
        widgets = {
            'area_description': forms.Textarea(attrs={'rows': 2}),
        }


class CollectionZoneUpdateForm(forms.ModelForm):
    class Meta:
        model = CollectionZone
        fields = ('name', 'area_description', 'is_active')
        widgets = {
            'area_description': forms.Textarea(attrs={'rows': 2}),
        }


class CollectionRouteForm(forms.ModelForm):
    class Meta:
        model = CollectionRoute
        fields = ('name', 'zone', 'vehicle', 'scheduled_date', 'status', 'notes')
        widgets = {
            'scheduled_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['vehicle'].required = False
        self.fields['vehicle'].queryset = Vehicle.objects.exclude(
            status=Vehicle.Status.MAINTENANCE,
        )

    def clean(self):
        cleaned_data = super().clean()
        vehicle = cleaned_data.get('vehicle')
        scheduled_date = cleaned_data.get('scheduled_date')
        route_status = cleaned_data.get('status')
        if vehicle and scheduled_date:
            existing_routes = CollectionRoute.objects.filter(
                vehicle=vehicle,
                scheduled_date=scheduled_date,
            ).exclude(
                status__in=(
                    CollectionRoute.Status.COMPLETED,
                    CollectionRoute.Status.CANCELLED,
                ),
            )
            if self.instance.pk:
                existing_routes = existing_routes.exclude(pk=self.instance.pk)
            if existing_routes.exists():
                self.add_error('vehicle', 'This vehicle already has a route on that date.')
        if vehicle and route_status == CollectionRoute.Status.ACTIVE:
            active_routes = CollectionRoute.objects.filter(
                vehicle=vehicle,
                status=CollectionRoute.Status.ACTIVE,
            )
            if self.instance.pk:
                active_routes = active_routes.exclude(pk=self.instance.pk)
            if active_routes.exists():
                self.add_error('vehicle', 'This vehicle is already on an active route.')
        return cleaned_data


class RouteStopForm(forms.ModelForm):
    class Meta:
        model = RouteStop
        fields = ('route', 'pickup', 'stop_order')
        widgets = {
            'stop_order': forms.NumberInput(attrs={'min': '1'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['route'].queryset = CollectionRoute.objects.exclude(
            status__in=(
                CollectionRoute.Status.COMPLETED,
                CollectionRoute.Status.CANCELLED,
            ),
        ).order_by('scheduled_date', 'name')
        self.fields['pickup'].queryset = PickupRequest.objects.filter(
            status=PickupRequest.Status.APPROVED,
        ).select_related('user', 'zone').order_by('pickup_date', 'created_at')


class LocationUpdateForm(forms.ModelForm):
    class Meta:
        model = LocationUpdate
        fields = (
            'route',
            'checkpoint',
            'latitude',
            'longitude',
            'route_status',
            'notes',
        )
        widgets = {
            'latitude': forms.NumberInput(attrs={'min': '-90', 'max': '90', 'step': '0.000001'}),
            'longitude': forms.NumberInput(attrs={'min': '-180', 'max': '180', 'step': '0.000001'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['latitude'].required = False
        self.fields['longitude'].required = False
        self.fields['route'].queryset = CollectionRoute.objects.exclude(
            status__in=(
                CollectionRoute.Status.COMPLETED,
                CollectionRoute.Status.CANCELLED,
            ),
        ).order_by('scheduled_date', 'name')


class RecyclingRecordForm(forms.ModelForm):
    sorted_weight_kg = forms.DecimalField(
        min_value=0,
        max_digits=9,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={'min': '0', 'step': '0.01'}),
    )

    class Meta:
        model = RecyclingRecord
        fields = ('classification', 'sorted_weight_kg', 'stage', 'notes')
        widgets = {
            'sorted_weight_kg': forms.NumberInput(attrs={'min': '0', 'step': '0.01'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def clean(self):
        cleaned_data = super().clean()
        classification = cleaned_data.get('classification')
        stage = cleaned_data.get('stage')
        sorted_weight = cleaned_data.get('sorted_weight_kg')
        if (
            classification == RecyclingRecord.Classification.RECYCLABLE
            and stage in (
                RecyclingRecord.Stage.SORTED,
                RecyclingRecord.Stage.PROCESSING,
                RecyclingRecord.Stage.RECYCLED,
            )
            and sorted_weight is None
        ):
            self.add_error('sorted_weight_kg', 'Enter the weight that was sorted.')
        return cleaned_data


class CompostBatchForm(forms.ModelForm):
    class Meta:
        model = CompostBatch
        fields = (
            'batch_code',
            'source_pickups',
            'input_weight_kg',
            'yield_kg',
            'status',
            'notes',
        )
        widgets = {
            'source_pickups': forms.SelectMultiple(attrs={'size': 5}),
            'input_weight_kg': forms.NumberInput(attrs={'min': '0.01', 'step': '0.01'}),
            'yield_kg': forms.NumberInput(attrs={'min': '0', 'step': '0.01'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        eligible_pickups = PickupRequest.objects.filter(
            status=PickupRequest.Status.COMPLETED,
            category__name__iexact='Organic',
        )
        if self.instance.pk:
            eligible_pickups = eligible_pickups.filter(
                Q(compost_batches__isnull=True)
                | Q(compost_batches=self.instance)
            )
        else:
            eligible_pickups = eligible_pickups.filter(compost_batches__isnull=True)
        self.fields['source_pickups'].queryset = eligible_pickups.select_related(
            'user',
        ).order_by('-created_at').distinct()


class CompostProductForm(forms.ModelForm):
    class Meta:
        model = CompostProduct
        fields = (
            'name',
            'description',
            'compost_batch',
            'price_per_kg',
            'stock_kg',
            'is_active',
        )
        widgets = {
            'price_per_kg': forms.NumberInput(attrs={'min': '0', 'step': '0.01'}),
            'stock_kg': forms.NumberInput(attrs={'min': '0', 'step': '0.01'}),
            'description': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ready_batches = CompostBatch.objects.all()
        if self.instance.pk and self.instance.compost_batch_id:
            ready_batches = ready_batches.filter(
                Q(pk=self.instance.compost_batch_id)
                | Q(status=CompostBatch.Status.READY),
            )
        else:
            ready_batches = ready_batches.filter(
                status=CompostBatch.Status.READY,
            )
        self.fields['compost_batch'].queryset = ready_batches.order_by('batch_code')


class SalesOrderForm(forms.ModelForm):
    class Meta:
        model = SalesOrder
        fields = ('product', 'quantity_kg')
        widgets = {
            'quantity_kg': forms.NumberInput(attrs={'min': '0.01', 'step': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product'].queryset = CompostProduct.objects.filter(
            is_active=True,
            stock_kg__gt=0,
        ).order_by('name')
