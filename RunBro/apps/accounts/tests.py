from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class RegistrationViewTests(TestCase):
    def test_registration_page_is_available(self):
        response = self.client.get(reverse('register'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/register.html')

    def test_valid_registration_creates_and_authenticates_user(self):
        response = self.client.post(
            reverse('register'),
            {
                'username': 'new-runner',
                'email': 'runner@example.com',
                'password1': 'SafeRunBroPass!2026',
                'password2': 'SafeRunBroPass!2026',
            },
        )

        self.assertRedirects(response, reverse('plan_list'))
        user = User.objects.get(username='new-runner')
        self.assertEqual(user.email, 'runner@example.com')
        self.assertTrue(user.check_password('SafeRunBroPass!2026'))
        self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))


class LoginViewTests(TestCase):
    def test_login_page_is_available(self):
        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/login.html')

    def test_valid_login_authenticates_user(self):
        user = User.objects.create_user(
            username='existing-runner',
            password='another-safe-password-123',
        )

        response = self.client.post(
            reverse('login'),
            {
                'username': 'existing-runner',
                'password': 'another-safe-password-123',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))


class LogoutViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='logout-runner',
            password='another-safe-password-123',
        )
        self.client.force_login(self.user)

    def test_logout_requires_post(self):
        response = self.client.get(reverse('logout'))

        self.assertEqual(response.status_code, 405)
        self.assertIn('_auth_user_id', self.client.session)

    def test_post_logout_ends_session(self):
        response = self.client.post(reverse('logout'))

        self.assertRedirects(response, reverse('home'))
        self.assertNotIn('_auth_user_id', self.client.session)
