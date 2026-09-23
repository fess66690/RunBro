from django.contrib import admin

from .models import RaceType, VdotReference, StandardPlanTemplate, GeneratedPlan


@admin.register(RaceType)
class RaceTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'distance_km', 'default_plan_weeks')
    ordering = ('distance_km',)


@admin.register(VdotReference)
class VdotReferenceAdmin(admin.ModelAdmin):
    list_display = (
        'vdot_value',
        'easy_pace_sec',
        'marathon_pace_sec',
        'threshold_pace_sec',
        'interval_pace_sec',
        'repetition_pace_200m_sec',
        'fast_reps_pace_200m_sec',
    )
    ordering = ('vdot_value',)
    search_fields = ('vdot_value',)


@admin.register(StandardPlanTemplate)
class StandardPlanTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'race_type', 'weeks_count', 'is_default', 'created_at')
    list_filter = ('race_type', 'is_default')
    search_fields = ('name',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(GeneratedPlan)
class GeneratedPlanAdmin(admin.ModelAdmin):
    list_display = ('user', 'goal_race', 'snapshot_vdot', 'is_active', 'created_at')
    list_filter = ('goal_race', 'is_active')
    search_fields = ('user__username',)
    readonly_fields = ('created_at', 'updated_at', 'plan_data')