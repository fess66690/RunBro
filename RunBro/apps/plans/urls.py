from django.urls import path

from . import views

urlpatterns = [
    path('', views.plan_list, name='plan_list'),
    path('create/', views.plan_create, name='plan_create'),
    path('<int:pk>/workouts/complete/', views.complete_workout, name='workout_complete'),
    path('<int:pk>/adjust/', views.adjust_plan, name='plan_adjust'),
    path('<int:pk>/delete/', views.delete_plan, name='plan_delete'),
    path('<int:pk>/', views.plan_detail, name='plan_detail'),
]