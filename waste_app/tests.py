from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

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


class WasteAppWorkflowTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            username='member@example.com',
            email='member@example.com',
            password='Existing-user-Password-984!',
            first_name='Test',
            last_name='Member',
        )
        self.profile = UserProfile.objects.create(
            user=self.user,
            phone='555-0123',
            address='12 Green Street',
        )
        self.category, _ = WasteCategory.objects.get_or_create(
            name='Organic',
            defaults={
                'description': 'Food scraps, coffee grounds, and yard trimmings.',
                'points_per_kg': 15,
            },
        )

    def test_registration_creates_user_profile_and_signs_user_in(self):
        response = self.client.post(
            reverse('register'),
            {
                'fullName': 'New Member',
                'phone': '555-0199',
                'email': 'new-member@example.com',
                'address': '42 Recycling Lane',
                'password': 'Unique-Registration-Pass-984!',
                'confirmPassword': 'Unique-Registration-Pass-984!',
                'terms': 'on',
            },
        )

        self.assertRedirects(response, reverse('user_dashboard'))
        new_user = self.user_model.objects.get(email='new-member@example.com')
        self.assertEqual(new_user.profile.phone, '555-0199')
        self.assertEqual(new_user.profile.address, '42 Recycling Lane')
        self.assertEqual(int(self.client.session['_auth_user_id']), new_user.pk)

    def test_email_login_redirects_regular_and_staff_users(self):
        response = self.client.post(
            reverse('login'),
            {'email': self.user.email, 'password': 'Existing-user-Password-984!', 'remember': 'on'},
        )
        self.assertRedirects(response, reverse('user_dashboard'))

        staff_user = self.user_model.objects.create_user(
            username='operator@example.com',
            email='operator@example.com',
            password='Operator-Password-984!',
            is_staff=True,
        )
        self.client.post(reverse('logout'))
        response = self.client.post(
            reverse('login'),
            {'email': staff_user.email, 'password': 'Operator-Password-984!'},
        )
        self.assertRedirects(response, reverse('admin_dashboard'))
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_login_accepts_username_and_redirects_superusers_to_custom_admin(self):
        self.user.username = 'dasun'
        self.user.save(update_fields=['username'])

        response = self.client.get(reverse('login'))
        self.assertContains(response, 'Email or username')
        self.assertContains(response, 'type="text" name="email"')
        response = self.client.post(
            reverse('login'),
            {'email': 'dasun', 'password': 'Existing-user-Password-984!'},
        )
        self.assertRedirects(response, reverse('user_dashboard'))
        self.assertEqual(self.client.get(reverse('user_dashboard')).status_code, 200)

        self.client.post(reverse('logout'))
        superuser = self.user_model.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='Superuser-Password-984!',
        )
        response = self.client.post(
            reverse('login'),
            {'email': 'admin', 'password': 'Superuser-Password-984!'},
        )
        self.assertRedirects(response, reverse('admin_dashboard'))
        admin_response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(admin_response.status_code, 200)
        self.assertTemplateUsed(admin_response, 'waste_app/admin_dashboard.html')
        self.assertEqual(admin_response.wsgi_request.user, superuser)
        self.assertEqual(self.client.get(reverse('dispatch_dashboard')).status_code, 200)

    def test_user_can_submit_and_cancel_their_pickup(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('user_dashboard'),
            {
                'category': self.category.pk,
                'weight': '2.50',
                'date': date.today().isoformat(),
                'timeSlot': PickupRequest.TimeSlot.MORNING,
                'address': '42 Recycling Lane',
            },
        )
        self.assertRedirects(response, reverse('user_dashboard'))
        pickup = PickupRequest.objects.get(user=self.user)
        self.assertEqual(pickup.estimated_weight_kg, Decimal('2.50'))
        self.assertTrue(
            UserNotification.objects.filter(
                recipient=self.user,
                pickup=pickup,
                category=UserNotification.Category.SCHEDULE,
            ).exists(),
        )

        response = self.client.post(reverse('cancel_pickup', args=[pickup.pk]))
        self.assertRedirects(response, reverse('user_dashboard'))
        pickup.refresh_from_db()
        self.assertEqual(pickup.status, PickupRequest.Status.CANCELLED)
        self.assertTrue(
            UserNotification.objects.filter(
                recipient=self.user,
                pickup=pickup,
                category=UserNotification.Category.STATUS,
            ).exists(),
        )

    def test_bulk_pickup_saves_customer_tier_zone_weight_and_notes(self):
        zone = CollectionZone.objects.create(
            name='Harbor District',
            area_description='Hotels and coastal businesses.',
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('user_dashboard'),
            {
                'category': self.category.pk,
                'customer_type': PickupRequest.CustomerType.HOTEL,
                'customer_tier': PickupRequest.CustomerTier.COMMERCIAL,
                'zone': zone.pk,
                'bulk_weight': '125.50',
                'special_handling_notes': 'Use the loading entrance.',
                'date': date.today().isoformat(),
                'timeSlot': PickupRequest.TimeSlot.AFTERNOON,
                'address': '1 Harbor Road',
            },
        )

        self.assertRedirects(response, reverse('user_dashboard'))
        pickup = PickupRequest.objects.get(user=self.user)
        self.assertEqual(pickup.customer_type, PickupRequest.CustomerType.HOTEL)
        self.assertEqual(pickup.customer_tier, PickupRequest.CustomerTier.COMMERCIAL)
        self.assertEqual(pickup.bulk_weight_kg, Decimal('125.50'))
        self.assertEqual(pickup.estimated_weight_kg, Decimal('125.50'))
        self.assertEqual(pickup.zone, zone)
        self.assertEqual(pickup.special_handling_notes, 'Use the loading entrance.')
        self.client.force_login(self.user)
        tracking_response = self.client.get(reverse('user_dashboard'))
        self.assertContains(tracking_response, 'Awaiting dispatch assignment')
        self.assertContains(tracking_response, '1 Harbor Road')
        self.assertContains(tracking_response, 'Harbor District')
        self.assertContains(tracking_response, 'Afternoon 1PM-5PM')

        staff_user = self.user_model.objects.create_user(
            username='hotel-dispatch@example.com',
            email='hotel-dispatch@example.com',
            password='Hotel-Dispatch-Password-984!',
            is_staff=True,
        )
        self.client.force_login(staff_user)
        response = self.client.post(
            reverse('update_pickup_status', args=[pickup.pk]),
            {'status': PickupRequest.Status.APPROVED, 'return_to': 'dispatch'},
        )
        self.assertRedirects(
            response,
            f'{reverse("dispatch_dashboard")}#bulk-requests',
        )
        pickup.refresh_from_db()
        self.assertEqual(pickup.status, PickupRequest.Status.APPROVED)

    def test_dispatch_routes_location_eta_and_recycling_points(self):
        staff_user = self.user_model.objects.create_user(
            username='dispatcher@example.com',
            email='dispatcher@example.com',
            password='Dispatcher-Password-984!',
            is_staff=True,
        )
        self.client.force_login(staff_user)
        self.assertContains(self.client.get(reverse('dispatch_dashboard')), 'Fleet &amp; Recycling Dispatch')

        response = self.client.post(
            reverse('create_zone'),
            {'name': 'Central Zone', 'area_description': 'Central municipal collection area.'},
        )
        self.assertRedirects(response, f'{reverse("dispatch_dashboard")}#zones')
        zone = CollectionZone.objects.get(name='Central Zone')

        response = self.client.post(
            reverse('update_zone', args=[zone.pk]),
            {
                'name': zone.name,
                'area_description': 'Updated central collection area.',
                'is_active': 'on',
            },
        )
        self.assertRedirects(response, f'{reverse("dispatch_dashboard")}#zones')
        zone.refresh_from_db()
        self.assertEqual(zone.area_description, 'Updated central collection area.')
        self.assertTrue(zone.is_active)

        response = self.client.post(
            reverse('create_vehicle'),
            {
                'vehicle_code': 'CF-TRK-01',
                'capacity_kg': '10.00',
                'operator_name': 'Dispatch Driver',
                'status': Vehicle.Status.AVAILABLE,
            },
        )
        self.assertRedirects(response, f'{reverse("dispatch_dashboard")}#vehicles')
        vehicle = Vehicle.objects.get(vehicle_code='CF-TRK-01')
        pickup = PickupRequest.objects.create(
            user=self.user,
            category=self.category,
            zone=zone,
            pickup_address='12 Green Street',
            pickup_date=date.today(),
            time_slot=PickupRequest.TimeSlot.MORNING,
            estimated_weight_kg=Decimal('3.00'),
            status=PickupRequest.Status.APPROVED,
        )

        response = self.client.post(
            reverse('create_route'),
            {
                'name': 'Central Morning Run',
                'zone': zone.pk,
                'vehicle': vehicle.pk,
                'scheduled_date': date.today().isoformat(),
                'status': CollectionRoute.Status.PLANNED,
                'notes': '',
            },
        )
        self.assertRedirects(response, f'{reverse("dispatch_dashboard")}#routes')
        route = CollectionRoute.objects.get(name='Central Morning Run')

        response = self.client.post(
            reverse('assign_route_stop'),
            {'route': route.pk, 'pickup': pickup.pk, 'stop_order': 1},
        )
        self.assertRedirects(response, f'{reverse("dispatch_dashboard")}#routes')
        stop = RouteStop.objects.get(pickup=pickup)
        self.assertEqual(stop.route, route)
        self.assertEqual(stop.estimated_arrival.hour, 8)

        response = self.client.post(
            reverse('add_location_update'),
            {
                'route': route.pk,
                'checkpoint': 'Central Sorting Center',
                'latitude': '6.927100',
                'longitude': '79.861200',
                'route_status': CollectionRoute.Status.ACTIVE,
                'notes': 'Vehicle departed.',
            },
        )
        self.assertRedirects(response, f'{reverse("dispatch_dashboard")}#tracking')
        update = LocationUpdate.objects.get(route=route)
        self.assertEqual(update.checkpoint, 'Central Sorting Center')
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, Vehicle.Status.ON_ROUTE)
        self.assertEqual(vehicle.current_latitude, Decimal('6.927100'))
        response = self.client.get(reverse('admin_dashboard'))
        self.assertContains(response, 'Live Collection Location &amp; Vehicle Tracking')
        self.assertContains(response, 'CF-TRK-01')
        self.assertContains(response, 'Central Sorting Center')
        self.assertContains(response, '6.927100, 79.861200')

        self.client.force_login(self.user)
        response = self.client.get(reverse('user_dashboard'))
        self.assertContains(response, 'Central Morning Run')
        self.assertContains(response, 'Central Sorting Center')
        self.assertContains(response, 'ETA 8:00 AM')

        self.client.force_login(staff_user)
        response = self.client.post(
            reverse('update_pickup_status', args=[pickup.pk]),
            {'status': PickupRequest.Status.COMPLETED},
        )
        self.assertRedirects(response, reverse('admin_dashboard'))
        pickup.refresh_from_db()
        stop.refresh_from_db()
        route.refresh_from_db()
        vehicle.refresh_from_db()
        self.profile.refresh_from_db()
        record = RecyclingRecord.objects.get(pickup=pickup)
        self.assertEqual(stop.status, RouteStop.Status.COLLECTED)
        self.assertEqual(route.status, CollectionRoute.Status.COMPLETED)
        self.assertEqual(vehicle.status, Vehicle.Status.AVAILABLE)
        self.assertEqual(self.profile.eco_points, 45)
        self.assertEqual(record.eco_points_awarded, 45)

        response = self.client.post(
            reverse('update_vehicle_status', args=[vehicle.pk]),
            {'status': Vehicle.Status.MAINTENANCE},
        )
        self.assertRedirects(response, f'{reverse("dispatch_dashboard")}#vehicles')
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, Vehicle.Status.MAINTENANCE)
        self.client.post(
            reverse('update_vehicle_status', args=[vehicle.pk]),
            {'status': Vehicle.Status.AVAILABLE},
        )
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, Vehicle.Status.AVAILABLE)

        self.client.post(
            reverse('update_recycling_record', args=[pickup.pk]),
            {
                'classification': RecyclingRecord.Classification.NON_RECYCLABLE,
                'sorted_weight_kg': '3.00',
                'stage': RecyclingRecord.Stage.DISPOSED,
                'notes': 'Contaminated material.',
            },
        )
        self.profile.refresh_from_db()
        record.refresh_from_db()
        self.assertEqual(self.profile.eco_points, 0)
        self.assertEqual(record.eco_points_awarded, 0)

        self.client.post(
            reverse('update_recycling_record', args=[pickup.pk]),
            {
                'classification': RecyclingRecord.Classification.RECYCLABLE,
                'sorted_weight_kg': '1.20',
                'stage': RecyclingRecord.Stage.RECYCLED,
                'notes': 'Clean recyclable fraction.',
            },
        )
        self.profile.refresh_from_db()
        record.refresh_from_db()
        self.assertEqual(self.profile.eco_points, 18)
        self.assertEqual(record.calculate_eco_points(), 18)

    def test_route_assignment_rejects_vehicle_capacity_overflow(self):
        zone = CollectionZone.objects.create(name='North Zone')
        vehicle = Vehicle.objects.create(
            vehicle_code='CF-TRK-SMALL',
            capacity_kg=Decimal('2.00'),
            operator_name='Capacity Test Driver',
        )
        route = CollectionRoute.objects.create(
            name='North Route',
            zone=zone,
            vehicle=vehicle,
            scheduled_date=date.today(),
        )
        pickup = PickupRequest.objects.create(
            user=self.user,
            category=self.category,
            zone=zone,
            pickup_address='12 Green Street',
            pickup_date=date.today(),
            time_slot=PickupRequest.TimeSlot.MORNING,
            estimated_weight_kg=Decimal('3.00'),
            status=PickupRequest.Status.APPROVED,
        )
        staff_user = self.user_model.objects.create_user(
            username='capacity@example.com',
            email='capacity@example.com',
            password='Capacity-Password-984!',
            is_staff=True,
        )
        self.client.force_login(staff_user)

        response = self.client.post(
            reverse('assign_route_stop'),
            {'route': route.pk, 'pickup': pickup.pk, 'stop_order': 1},
        )

        self.assertRedirects(response, f'{reverse("dispatch_dashboard")}#routes')
        self.assertFalse(RouteStop.objects.filter(pickup=pickup).exists())
        self.assertTrue(
            any(
                'would exceed' in str(message)
                for message in response.wsgi_request._messages
            ),
        )

    def test_admin_completion_awards_points_only_once(self):
        staff_user = self.user_model.objects.create_user(
            username='operator@example.com',
            email='operator@example.com',
            password='Operator-Password-984!',
            is_staff=True,
        )
        pickup = PickupRequest.objects.create(
            user=self.user,
            category=self.category,
            pickup_address='42 Recycling Lane',
            pickup_date=date.today(),
            time_slot=PickupRequest.TimeSlot.MORNING,
            estimated_weight_kg=Decimal('2.50'),
        )
        self.client.force_login(staff_user)

        response = self.client.post(
            reverse('update_pickup_status', args=[pickup.pk]),
            {'status': PickupRequest.Status.COMPLETED},
        )
        self.assertRedirects(response, reverse('admin_dashboard'))
        self.profile.refresh_from_db()
        pickup.refresh_from_db()
        self.assertEqual(self.profile.eco_points, 38)
        self.assertTrue(pickup.points_awarded)
        self.assertIsNotNone(pickup.completed_at)

        self.client.post(
            reverse('update_pickup_status', args=[pickup.pk]),
            {'status': PickupRequest.Status.APPROVED},
        )
        self.client.post(
            reverse('update_pickup_status', args=[pickup.pk]),
            {'status': PickupRequest.Status.COMPLETED},
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.eco_points, 38)

    def test_guidelines_requires_authentication_and_shows_profile_points(self):
        response = self.client.get(reverse('guidelines'))
        self.assertRedirects(response, f'{reverse("login")}?next={reverse("guidelines")}')

        self.profile.eco_points = 125
        self.profile.save(update_fields=['eco_points'])
        PickupRequest.objects.create(
            user=self.user,
            category=self.category,
            pickup_address='12 Green Street',
            pickup_date=date.today(),
            time_slot=PickupRequest.TimeSlot.MORNING,
            estimated_weight_kg=Decimal('1.00'),
            status=PickupRequest.Status.REJECTED,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse('guidelines'))
        self.assertContains(response, '125 Eco-Points')
        self.assertContains(response, 'REQUEST REJECTED')
        self.assertContains(response, 'width: 100%')
        self.assertContains(response, 'Location &amp; Vehicle Tracking')
        self.assertContains(response, '12 Green Street')

    def test_profile_displays_metrics_and_updates_user_and_profile(self):
        self.client.force_login(self.user)
        PickupRequest.objects.create(
            user=self.user,
            category=self.category,
            pickup_address='42 Recycling Lane',
            pickup_date=date.today(),
            time_slot=PickupRequest.TimeSlot.MORNING,
            estimated_weight_kg=Decimal('2.50'),
            status=PickupRequest.Status.COMPLETED,
        )
        self.profile.eco_points = 125
        self.profile.save(update_fields=['eco_points'])

        response = self.client.get(reverse('profile'))
        self.assertContains(response, 'Eco-Points Balance')
        self.assertContains(response, '125')
        self.assertContains(response, '2.5')

        response = self.client.post(
            reverse('profile'),
            {
                'full_name': 'Updated Member',
                'phone': '555-0198',
                'address': '99 New Green Street',
            },
        )
        self.assertRedirects(response, reverse('profile'))
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.user.get_full_name(), 'Updated Member')
        self.assertEqual(self.profile.phone, '555-0198')
        self.assertEqual(self.profile.address, '99 New Green Street')

    def test_pickup_history_filter_only_changes_displayed_requests(self):
        pending = PickupRequest.objects.create(
            user=self.user,
            category=self.category,
            pickup_address='12 Green Street',
            pickup_date=date.today(),
            time_slot=PickupRequest.TimeSlot.MORNING,
            estimated_weight_kg=Decimal('1.00'),
        )
        completed = PickupRequest.objects.create(
            user=self.user,
            category=self.category,
            pickup_address='12 Green Street',
            pickup_date=date.today(),
            time_slot=PickupRequest.TimeSlot.AFTERNOON,
            estimated_weight_kg=Decimal('3.00'),
            status=PickupRequest.Status.COMPLETED,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('user_dashboard'),
            {'status': PickupRequest.Status.COMPLETED},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_pickups'], 2)
        self.assertEqual(
            list(response.context['pickup_requests'].values_list('pk', flat=True)),
            [completed.pk],
        )
        self.assertEqual(response.context['tracking_pickup'].pk, pending.pk)

    def test_staff_can_create_and_update_categories_and_view_customers(self):
        staff_user = self.user_model.objects.create_user(
            username='operator@example.com',
            email='operator@example.com',
            password='Operator-Password-984!',
            is_staff=True,
        )
        self.client.force_login(staff_user)

        response = self.client.get(reverse('admin_dashboard'))
        self.assertContains(response, 'Registered Customers')
        self.assertContains(response, 'Waste Categories')
        self.assertContains(response, self.user.email)

        response = self.client.post(
            reverse('create_category'),
            {
                'name': 'Paper',
                'description': 'Clean paper and cardboard.',
                'points_per_kg': 12,
            },
        )
        self.assertRedirects(response, f'{reverse("admin_dashboard")}#categories')
        category = WasteCategory.objects.get(name='Paper')

        response = self.client.post(
            reverse('update_category', args=[category.pk]),
            {
                'name': 'Paper and Cardboard',
                'description': 'Clean paper, boxes, and cardboard.',
                'points_per_kg': 18,
            },
        )
        self.assertRedirects(response, f'{reverse("admin_dashboard")}#categories')
        category.refresh_from_db()
        self.assertEqual(category.name, 'Paper and Cardboard')
        self.assertEqual(category.points_per_kg, 18)

    def test_all_custom_pages_render_for_their_expected_users(self):
        home_response = self.client.get(reverse('home'))
        self.assertContains(home_response, 'KG DIVERTED')
        self.assertContains(home_response, 'href="/guidelines/"', count=3)
        self.assertContains(home_response, 'href="/login/"')
        self.assertContains(home_response, 'href="/register/"')
        self.assertEqual(self.client.get(reverse('login')).status_code, 200)
        self.assertEqual(self.client.get(reverse('register')).status_code, 200)

        self.client.force_login(self.user)
        self.assertContains(
            self.client.get(reverse('home')),
            'href="/dashboard/#schedule-pickup"',
        )
        self.assertEqual(self.client.get(reverse('user_dashboard')).status_code, 200)
        self.assertEqual(self.client.get(reverse('profile')).status_code, 200)
        self.assertEqual(self.client.get(reverse('guidelines')).status_code, 200)
        self.assertEqual(self.client.get(reverse('marketplace')).status_code, 200)
        self.assertEqual(self.client.get(reverse('notifications')).status_code, 200)
        for route_name in (
            'admin_dashboard',
            'dispatch_dashboard',
            'compost_management',
            'sales_management',
            'reports',
        ):
            self.assertRedirects(
                self.client.get(reverse(route_name)),
                f'{reverse("login")}?next={reverse(route_name)}',
            )

        staff_user = self.user_model.objects.create_user(
            username='operator@example.com',
            email='operator@example.com',
            password='Operator-Password-984!',
            is_staff=True,
        )
        self.client.force_login(staff_user)
        admin_response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(admin_response.status_code, 200)
        self.assertTemplateUsed(admin_response, 'waste_app/admin_dashboard.html')
        self.assertEqual(self.client.get(reverse('dispatch_dashboard')).status_code, 200)
        self.assertContains(self.client.get(reverse('compost_management')), 'Compost Management')
        self.assertContains(self.client.get(reverse('sales_management')), 'Waste Sales Management')
        self.assertContains(self.client.get(reverse('reports')), 'Reports &amp; Analytics')

    def test_compost_batch_readiness_product_sales_and_stock_reconciliation(self):
        staff_user = self.user_model.objects.create_user(
            username='compost-operator@example.com',
            email='compost-operator@example.com',
            password='Compost-Operator-Password-984!',
            is_staff=True,
        )
        pickup = PickupRequest.objects.create(
            user=self.user,
            category=self.category,
            pickup_address='12 Green Street',
            pickup_date=date.today(),
            time_slot=PickupRequest.TimeSlot.MORNING,
            estimated_weight_kg=Decimal('10.00'),
            status=PickupRequest.Status.COMPLETED,
        )
        self.client.force_login(staff_user)
        response = self.client.post(
            reverse('create_compost_batch'),
            {
                'batch_code': 'CF-COMP-001',
                'source_pickups': [pickup.pk],
                'input_weight_kg': '10.00',
                'yield_kg': '',
                'status': CompostBatch.Status.PROCESSING,
                'notes': 'Aerobic processing.',
            },
        )
        self.assertRedirects(response, f'{reverse("compost_management")}#batches')
        batch = CompostBatch.objects.get(batch_code='CF-COMP-001')
        self.assertEqual(list(batch.source_pickups.all()), [pickup])

        response = self.client.post(
            reverse('update_compost_batch', args=[batch.pk]),
            {
                'batch_code': batch.batch_code,
                'source_pickups': [pickup.pk],
                'input_weight_kg': '10.00',
                'yield_kg': '3.50',
                'status': CompostBatch.Status.READY,
                'notes': 'Cured and screened.',
            },
        )
        self.assertRedirects(response, f'{reverse("compost_management")}#batches')
        batch.refresh_from_db()
        self.assertEqual(batch.status, CompostBatch.Status.READY)
        self.assertEqual(batch.yield_kg, Decimal('3.50'))
        self.assertIsNotNone(batch.ready_at)
        self.assertTrue(
            UserNotification.objects.filter(
                recipient=self.user,
                pickup=pickup,
                title='Compost batch ready',
            ).exists(),
        )

        response = self.client.post(
            reverse('create_compost_product'),
            {
                'name': 'Garden Compost',
                'description': 'Screened compost.',
                'compost_batch': batch.pk,
                'price_per_kg': '4.25',
                'stock_kg': '20.00',
                'is_active': 'on',
            },
        )
        self.assertRedirects(response, f'{reverse("sales_management")}#products')
        product = CompostProduct.objects.get(name='Garden Compost')

        self.client.force_login(self.user)
        response = self.client.post(
            reverse('marketplace'),
            {'product': product.pk, 'quantity_kg': '25.00'},
        )
        self.assertRedirects(response, reverse('marketplace'))
        product.refresh_from_db()
        self.assertEqual(product.stock_kg, Decimal('20.00'))
        self.assertFalse(SalesOrder.objects.filter(user=self.user).exists())

        response = self.client.post(
            reverse('marketplace'),
            {'product': product.pk, 'quantity_kg': '4.50'},
        )
        self.assertRedirects(response, reverse('marketplace'))
        order = SalesOrder.objects.get(user=self.user, product=product)
        self.assertEqual(order.total_amount, Decimal('19.13'))
        product.refresh_from_db()
        self.assertEqual(product.stock_kg, Decimal('15.50'))
        self.assertTrue(order.stock_deducted)

        self.client.force_login(staff_user)
        response = self.client.post(
            reverse('update_sales_order', args=[order.pk]),
            {'status': SalesOrder.Status.APPROVED},
        )
        self.assertRedirects(response, f'{reverse("sales_management")}#orders')
        response = self.client.post(
            reverse('update_sales_order', args=[order.pk]),
            {'status': SalesOrder.Status.FULFILLED},
        )
        self.assertRedirects(response, f'{reverse("sales_management")}#orders')
        order.refresh_from_db()
        self.assertEqual(order.status, SalesOrder.Status.FULFILLED)

        self.client.force_login(self.user)
        self.client.post(
            reverse('marketplace'),
            {'product': product.pk, 'quantity_kg': '2.00'},
        )
        rejected_order = SalesOrder.objects.exclude(pk=order.pk).get(user=self.user)
        product.refresh_from_db()
        self.assertEqual(product.stock_kg, Decimal('13.50'))
        self.client.force_login(staff_user)
        self.client.post(
            reverse('update_sales_order', args=[rejected_order.pk]),
            {'status': SalesOrder.Status.REJECTED},
        )
        product.refresh_from_db()
        rejected_order.refresh_from_db()
        self.assertEqual(product.stock_kg, Decimal('15.50'))
        self.assertFalse(rejected_order.stock_deducted)
        self.assertTrue(
            UserNotification.objects.filter(
                recipient=self.user,
                order=order,
                category=UserNotification.Category.ORDER,
            ).exists(),
        )

    def test_notifications_are_private_readable_and_sales_dashboard_reports_real_data(self):
        staff_user = self.user_model.objects.create_user(
            username='reports@example.com',
            email='reports@example.com',
            password='Reports-Password-984!',
            is_staff=True,
        )
        pickup = PickupRequest.objects.create(
            user=self.user,
            category=self.category,
            pickup_address='12 Green Street',
            pickup_date=date.today(),
            time_slot=PickupRequest.TimeSlot.MORNING,
            estimated_weight_kg=Decimal('2.00'),
            status=PickupRequest.Status.COMPLETED,
        )
        UserNotification.objects.create(
            recipient=self.user,
            pickup=pickup,
            category=UserNotification.Category.STATUS,
            title='Collection complete',
            message='Your collection is complete.',
        )
        other_user = self.user_model.objects.create_user(
            username='other-member@example.com',
            email='other-member@example.com',
            password='Other-Member-Password-984!',
        )
        other_notification = UserNotification.objects.create(
            recipient=other_user,
            category=UserNotification.Category.SCHEDULE,
            title='Private schedule',
            message='Private notification.',
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('notifications'))
        self.assertContains(response, 'Collection complete')
        self.assertNotContains(response, 'Private schedule')
        notification = UserNotification.objects.get(recipient=self.user)
        response = self.client.post(
            reverse('mark_notification_read', args=[notification.pk]),
        )
        self.assertRedirects(response, reverse('notifications'))
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

        response = self.client.post(
            reverse('mark_notification_read', args=[other_notification.pk]),
        )
        self.assertEqual(response.status_code, 404)

        self.client.force_login(staff_user)
        response = self.client.get(reverse('reports'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['completed_pickup_count'], 1)
        self.assertEqual(response.context['collected_weight'], Decimal('2.00'))
        self.assertContains(response, 'Organic')

    def test_admin_can_activate_and_deactivate_customer_accounts(self):
        staff_user = self.user_model.objects.create_user(
            username='account-admin@example.com',
            email='account-admin@example.com',
            password='Account-Admin-Password-984!',
            is_staff=True,
        )
        self.client.force_login(staff_user)
        response = self.client.post(
            reverse('update_customer_access', args=[self.user.pk]),
            {'is_active': 'false'},
        )
        self.assertRedirects(response, f'{reverse("admin_dashboard")}#customers')
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

        response = self.client.post(
            reverse('update_customer_access', args=[self.user.pk]),
            {'is_active': 'true'},
        )
        self.assertRedirects(response, f'{reverse("admin_dashboard")}#customers')
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
