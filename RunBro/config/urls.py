from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import TemplateView

from apps.accounts.forms import LoginForm

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', TemplateView.as_view(template_name='home.html'), name='home'),
    path('plans/', include('apps.plans.urls')),
    path('accounts/', include('apps.accounts.urls')),

    # Явные auth-маршруты: не подключаем django.contrib.auth.urls целиком,
    # чтобы не дублировать имена и контролировать форму входа.
    path(
        'accounts/login/',
        auth_views.LoginView.as_view(
            template_name='registration/login.html',
            authentication_form=LoginForm,
        ),
        name='login',
    ),
    path(
        'accounts/logout/',
        auth_views.LogoutView.as_view(),
        name='logout',
    ),
    path(
        'accounts/password_change/',
        auth_views.PasswordChangeView.as_view(),
        name='password_change',
    ),
    path(
        'accounts/password_change/done/',
        auth_views.PasswordChangeDoneView.as_view(),
        name='password_change_done',
    ),
    path(
        'accounts/password_reset/',
        auth_views.PasswordResetView.as_view(),
        name='password_reset',
    ),
    path(
        'accounts/password_reset/done/',
        auth_views.PasswordResetDoneView.as_view(),
        name='password_reset_done',
    ),
    path(
        'accounts/reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(),
        name='password_reset_confirm',
    ),
    path(
        'accounts/reset/done/',
        auth_views.PasswordResetCompleteView.as_view(),
        name='password_reset_complete',
    ),
]
