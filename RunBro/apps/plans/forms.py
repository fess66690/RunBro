"""
Форма создания плана тренировок.
"""
from django import forms

from apps.plans.models import RaceType


class PlanCreateForm(forms.Form):
    """Форма выбора цели: дистанция + время."""

    race_type = forms.ModelChoiceField(
        queryset=RaceType.objects.all().order_by('distance_km'),
        label='Дистанция',
        empty_label='— Выбери дистанцию —',
        widget=forms.Select(attrs={'class': 'form-select form-select-lg'}),
    )

    hours = forms.IntegerField(
        min_value=0,
        max_value=10,
        initial=0,
        label='Часы',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0'}),
    )
    minutes = forms.IntegerField(
        min_value=0,
        max_value=59,
        initial=0,
        label='Минуты',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '30'}),
    )
    seconds = forms.IntegerField(
        min_value=0,
        max_value=59,
        initial=0,
        required=False,
        label='Секунды',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0'}),
    )

    def clean(self):
        cleaned = super().clean()
        h = cleaned.get('hours') or 0
        m = cleaned.get('minutes') or 0
        s = cleaned.get('seconds') or 0
        total = h * 3600 + m * 60 + s

        if total < 60:
            raise forms.ValidationError('Время должно быть не меньше 1 минуты.')

        cleaned['total_seconds'] = total
        return cleaned