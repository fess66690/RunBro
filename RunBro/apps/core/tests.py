from django.test import TestCase
from django.urls import reverse


class ThemeToggleTests(TestCase):
    def test_home_page_has_theme_toggle_and_initial_theme_script(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="theme-toggle"')
        self.assertContains(response, 'data-theme-icon')
        self.assertContains(response, 'js/theme.js')
        self.assertContains(response, 'runbro-theme')
