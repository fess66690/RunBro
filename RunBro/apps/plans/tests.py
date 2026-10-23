from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.plans.models import (
    CompletedWorkout,
    GeneratedPlan,
    RaceType,
    StandardPlanTemplate,
    VdotReference,
)
from apps.plans.services.plan_generator import (
    _parse_training_description,
    generate_plan,
)
from apps.plans.services.plan_service import (
    PlanGenerationError,
    adjust_plan_for_feedback,
    create_plan_for_user,
)


class PlanGeneratorTests(TestCase):
    Paces = {'E': 300, 'R': 50, 'I': 200, 'T': 240, 'M': 280, 'F': 45}

    @patch('apps.plans.services.plan_generator.get_paces', return_value=Paces)
    def test_vdot_group_selects_interval_boundaries(self, get_paces):
        structure = {
            'phases': [{
                'weeks': [{
                    'week': 7,
                    'trainings': [{
                        'day': 'T2',
                        'type': 'intervals',
                        'blocks': [
                            {'type': 'warmup', 'zone': 'E', 'distance_km': [1.5, 3]},
                            {
                                'type': 'interval', 'zone': 'I',
                                'distance_m': [800, 1000], 'repeats': [2, 5],
                            },
                        ],
                    }],
                }],
            }],
        }
        expected = {
            45: (1.5, 800, 2),
            46: (2.25, 900, 4),
            70: (2.25, 900, 4),
            71: (3, 1000, 5),
        }

        for vdot, (distance_km, distance_m, repeats) in expected.items():
            with self.subTest(vdot=vdot):
                plan = generate_plan(structure, vdot)
                blocks = plan['phases'][0]['weeks'][0]['trainings'][0]['blocks']
                self.assertEqual(blocks[0]['distance_km'], distance_km)
                self.assertEqual(blocks[1]['distance_m'], distance_m)
                self.assertEqual(blocks[1]['repeats'], repeats)

    @patch('apps.plans.services.plan_generator.get_paces', return_value=Paces)
    def test_series_volume_uses_vdot_group_and_weekly_mileage(self, get_paces):
        sequence = [
            {'distance_m': 200, 'zone': 'R', 'label': '200 м в Пв-темпе'},
            {'distance_m': 200, 'zone': 'E', 'label': '200 м бега трусцой'},
            {'distance_m': 400, 'zone': 'R', 'label': '1 × 400 м в Пв-темпе'},
            {'distance_m': 400, 'zone': 'E', 'label': '400 м бега трусцой'},
        ]
        structure = {
            'phases': [{
                'weeks': [{
                    'week': 7,
                    'trainings': [
                        {
                            'day': 'T1', 'type': 'series', 'zone': 'R',
                            'series_config': {
                                'target_zone': 'R',
                                'target_weekly_percent': [3, 5],
                                'max_work_km': 8,
                                'sequence': sequence,
                            },
                        },
                        {
                            'day': 'T2', 'type': 'easy',
                            'blocks': [{'type': 'easy', 'zone': 'E', 'distance_km': 20}],
                        },
                    ],
                }],
            }],
        }

        expected_repeats = {45: 1, 46: 1, 70: 1, 71: 2}
        for vdot, repeats in expected_repeats.items():
            with self.subTest(vdot=vdot):
                plan = generate_plan(structure, vdot)
                training = plan['phases'][0]['weeks'][0]['trainings'][0]
                self.assertEqual(training['total_repeats'], repeats)
                self.assertEqual(training['series_work_km'], repeats * 0.6)
                self.assertIn(f'Серии из {repeats} ×', training['description'])

        structure['phases'][0]['weeks'][0]['trainings'][1]['blocks'][0]['distance_km'] = 1000
        capped_plan = generate_plan(structure, 71)
        capped_training = capped_plan['phases'][0]['weeks'][0]['trainings'][0]
        self.assertEqual(capped_training['total_repeats'], 13)
        self.assertLessEqual(capped_training['series_work_km'], 8)

    @patch('apps.plans.services.plan_generator.get_paces', return_value=Paces)
    def test_description_only_series_adapts_to_vdot_and_weekly_volume(self, get_paces):
        structure = {
            'phases': [{
                'weeks': [{
                    'week': 7,
                    'trainings': [
                        {
                            'day': 'T1', 'type': 'intervals', 'zone': 'I',
                            'description': (
                                'Серии из 1000, 1200 или 1600 м в И-темпе '
                                '+ 3, 4 или 5 мин бега трусцой'
                            ),
                            'constraint': 'Общая дистанция в И-темпе — не более 8% недельного километража',
                        },
                        {
                            'day': 'T2', 'type': 'easy',
                            'blocks': [{'type': 'easy', 'zone': 'E', 'distance_km': 50}],
                        },
                    ],
                }],
            }],
        }
        expected = {45: (1000, 4), 46: (1200, 3), 71: (1600, 2)}

        for vdot, (distance_m, repeats) in expected.items():
            with self.subTest(vdot=vdot):
                plan = generate_plan(structure, vdot)
                training = plan['phases'][0]['weeks'][0]['trainings'][0]
                self.assertEqual(training['series_config']['sequence'][0]['distance_m'], distance_m)
                self.assertEqual(training['total_repeats'], repeats)
                self.assertLessEqual(training['series_work_km'], 4)
                self.assertLessEqual(training['series_work_km'] / (50 + training['total_km']), 0.08)

    @patch('apps.plans.services.plan_generator.get_paces', return_value=Paces)
    def test_block_intervals_are_reduced_to_weekly_volume_limit(self, get_paces):
        structure = {
            'phases': [{
                'weeks': [{
                    'week': 7,
                    'trainings': [
                        {
                            'day': 'T1', 'type': 'intervals',
                            'constraint': 'Общая дистанция в И-темпе — не более 8% недельного километража',
                            'blocks': [
                                {'type': 'warmup', 'zone': 'E', 'distance_km': 1},
                                {'type': 'interval', 'zone': 'I', 'distance_m': 1000, 'repeats': 10},
                                {'type': 'cooldown', 'zone': 'E', 'distance_km': 1},
                            ],
                        },
                        {
                            'day': 'T2', 'type': 'easy',
                            'blocks': [{'type': 'easy', 'zone': 'E', 'distance_km': 20}],
                        },
                        {
                            'day': 'T3', 'type': 'easy',
                            'blocks': [{'type': 'easy', 'zone': 'E', 'distance_km': 20}],
                        },
                    ],
                }],
            }],
        }

        plan = generate_plan(structure, 50)
        training = plan['phases'][0]['weeks'][0]['trainings'][0]
        interval = training['blocks'][1]
        self.assertEqual(interval['repeats'], 3)
        self.assertTrue(training['volume_limit_applied'])
        self.assertLessEqual(interval['total_km'], training['volume_limit_km'])


    def test_description_parser_understands_pace_modifiers_and_ranges(self):
        description = (
            '2 × (600 м Пв+3 + 600 м трусцой) + '
            '3 × (400 м Пв−1 + 400 м трусцой) + '
            '4 × (300 м Пв + 300 м трусцой) + '
            '6 × (200 м Б + 200 м трусцой)'
        )

        total_km, work_km = _parse_training_description(
            description,
            self.Paces,
            'confident',
        )

        self.assertAlmostEqual(total_km, 9.6)
        self.assertAlmostEqual(work_km, 4.8)

    @patch('apps.plans.services.plan_generator.get_paces', return_value=Paces)
    def test_description_only_fartlek_gets_estimated_volume(self, get_paces):
        structure = {
            'phases': [{
                'weeks': [{
                    'week': 7,
                    'trainings': [{
                        'day': 'T1',
                        'type': 'fartlek',
                        'zone': 'I',
                        'description': (
                            'Серии из 2 мин И, 1 мин трусцой + '
                            '1 мин И, 30 с трусцой + 30 с И, 30 с трусцой'
                        ),
                    }],
                }],
            }],
        }

        plan = generate_plan(structure, 60)
        training = plan['phases'][0]['weeks'][0]['trainings'][0]

        self.assertGreater(training['total_km'], 0)
        self.assertTrue(training['volume_estimated'])
        self.assertNotIn('volume_unknown', training)

    @patch('apps.plans.services.plan_generator.get_paces', return_value=Paces)
    def test_long_run_note_with_duration_gets_volume(self, get_paces):
        structure = {
            'phases': [{
                'weeks': [{
                    'week': 7,
                    'trainings': [
                        {
                            'day': 'T1',
                            'type': 'long_run',
                            'blocks': [{
                                'type': 'long',
                                'note': 'Д-забег; 2 ч',
                            }],
                        },
                        {
                            'day': 'T2',
                            'type': 'easy',
                            'blocks': [{
                                'type': 'easy',
                                'zone': 'E',
                                'distance_km': 10,
                            }],
                        },
                    ],
                }],
            }],
        }

        plan = generate_plan(structure, 60)
        long_run = plan['phases'][0]['weeks'][0]['trainings'][0]

        self.assertEqual(long_run['total_km'], 24)
        self.assertTrue(long_run['volume_estimated'])

    @patch('apps.plans.services.plan_generator.get_paces', return_value=Paces)
    def test_long_run_explicit_duration_wins_over_unreliable_percentage(self, get_paces):
        structure = {
            'phases': [{
                'weeks': [{
                    'week': 7,
                    'trainings': [
                        {
                            'day': 'T1',
                            'type': 'long_run',
                            'blocks': [{
                                'type': 'long',
                                'note': (
                                    'Д-забег; 2 ч или 25% недельного '
                                    'километража — что меньше'
                                ),
                            }],
                        },
                        {
                            'day': 'T2',
                            'type': 'easy',
                            'blocks': [{
                                'type': 'easy',
                                'zone': 'E',
                                'distance_km': 10,
                            }],
                        },
                    ],
                }],
            }],
        }

        plan = generate_plan(structure, 60)
        long_run = plan['phases'][0]['weeks'][0]['trainings'][0]

        self.assertEqual(long_run['total_km'], 24)
        self.assertTrue(long_run['volume_estimated'])

    @patch('apps.plans.services.plan_generator.get_paces', return_value=Paces)
    def test_long_run_percentage_without_enough_base_stays_unknown(self, get_paces):
        structure = {
            'phases': [{
                'weeks': [{
                    'week': 7,
                    'trainings': [
                        {
                            'day': 'T1',
                            'type': 'long_run',
                            'blocks': [{
                                'type': 'long',
                                'note': 'Д-забег; 20% недельного километража',
                            }],
                        },
                        {
                            'day': 'T2',
                            'type': 'easy',
                            'blocks': [{
                                'type': 'easy',
                                'zone': 'E',
                                'distance_km': 10,
                            }],
                        },
                    ],
                }],
            }],
        }

        plan = generate_plan(structure, 60)
        long_run = plan['phases'][0]['weeks'][0]['trainings'][0]

        self.assertIsNone(long_run['total_km'])
        self.assertTrue(long_run['volume_unknown'])


class WorkoutCompletionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='runner', password='SafeTestPass!2026')
        self.race_type = RaceType.objects.create(name='5km', distance_km=5)
        self.template = StandardPlanTemplate.objects.create(
            name='Тестовый план 5 км',
            race_type=self.race_type,
            structure={'phases': []},
        )
        self.plan = GeneratedPlan.objects.create(
            user=self.user,
            template=self.template,
            snapshot_vdot=40,
            goal_race='5km',
            plan_data={
                'phases': [
                    {
                        'phase': 1,
                        'name': 'Базовая',
                        'weeks': [
                            {
                                'week': 1,
                                'trainings': [
                                    {
                                        'day': 'T1',
                                        'type': 'easy',
                                        'blocks': [
                                            {'type': 'warmup', 'pace_formatted': '6:00'},
                                            {'type': 'interval', 'pace_formatted': '4:00'},
                                            {'type': 'cooldown', 'pace_formatted': '6:00'},
                                        ],
                                    },
                                    {'day': 'T2', 'type': 'mixed_or_race'},
                                ],
                            },
                            {'week': '2-3', 'description': 'Плановые недели'},
                        ],
                    },
                ],
            },
        )
        self.client.force_login(self.user)

    def test_plan_detail_shows_progress_for_individual_workouts(self):
        CompletedWorkout.objects.create(plan=self.plan, workout_key='0:0:0')

        response = self.client.get(reverse('plan_detail', args=[self.plan.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_workouts'], 3)
        self.assertEqual(response.context['completed_workouts'], 1)
        self.assertEqual(response.context['progress_percent'], 33)
        self.assertContains(response, '✓ Выполнено')
        self.assertContains(response, 'Отметить выполненной')
        self.assertContains(response, 'Недоступно')
        self.assertContains(response, 'Чувствую усталость')
        self.assertContains(response, 'Очень легко')
        self.assertContains(response, 'Смешанная или соревновательная тренировка')
        self.assertContains(response, 'Работа №1')
        self.assertContains(response, 'Работа №2')
        self.assertContains(response, 'Разминка')
        self.assertContains(response, 'Интервальный отрезок')
        self.assertContains(response, 'Заминка')
        self.assertContains(response, 'Тренировочный блок по описанию')
        self.assertNotContains(response, 'Mixed_Or_Race')
        self.assertContains(response, 'Печать плана')
        self.assertContains(response, 'Экспорт в PDF')
        response_html = response.content.decode()
        self.assertLess(
            response_html.index('Прогресс выполнения'),
            response_html.index('План подготовки'),
        )

    def test_plan_detail_uses_adjusted_block_distance(self):
        self.plan.plan_data = {
            'phases': [{
                'phase': 1,
                'weeks': [{
                    'week': 1,
                    'trainings': [{
                        'day': 'T1',
                        'type': 'easy',
                        'blocks': [{
                            'type': 'easy',
                            'zone': 'E',
                            'distance_km': 10,
                            'total_km': 9,
                            'pace_formatted': '6:00 /км',
                        }],
                    }],
                }],
            }],
        }
        self.plan.save(update_fields=['plan_data'])

        response = self.client.get(reverse('plan_detail', args=[self.plan.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '9 км')
        self.assertNotContains(response, '10 км')

    def test_plan_detail_renders_unknown_volume_rest_and_note(self):
        self.plan.plan_data = {
            'phases': [{
                'phase': 1,
                'name': 'База',
                'weeks': [{
                    'week': 1,
                    'trainings': [{
                        'day': 'T1',
                        'type': 'long_run',
                        'volume_unknown': True,
                        'blocks': [{
                            'type': 'long',
                            'note': 'Д-забег 25% недельного километража',
                            'rest_type': 'jog',
                            'rest_sec': 90,
                        }],
                    }],
                }, {
                    'week': 2,
                    'description': '7 дней по 30 минут в Л-темпе',
                    'trainings': [],
                }],
            }],
        }
        self.plan.save(update_fields=['plan_data'])

        response = self.client.get(reverse('plan_detail', args=[self.plan.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'объём не рассчитан')
        self.assertContains(response, 'Д-забег 25% недельного километража')
        self.assertContains(response, 'отдых: бег трусцой / 90 сек')
        self.assertContains(response, 'не включён в сумму')
        self.assertContains(response, 'Недельные блоки без детализации')

    def test_total_weeks_supports_dash_variants(self):
        self.plan.plan_data = {
            'phases': [{
                'weeks': [
                    {'week': '1–3'},
                    {'week': '5 - 6'},
                    {'week': 7},
                ],
            }],
        }

        self.assertEqual(self.plan.total_weeks, 6)

    @patch('apps.plans.services.plan_service.generate_plan')
    def test_adjustment_copies_valid_completion_progress(self, generate_plan):
        generate_plan.return_value = self.plan.plan_data
        CompletedWorkout.objects.create(plan=self.plan, workout_key='0:0:0')
        CompletedWorkout.objects.create(plan=self.plan, workout_key='old:missing')

        new_plan = adjust_plan_for_feedback(self.plan, -0.1)

        self.assertTrue(
            CompletedWorkout.objects.filter(
                plan=new_plan,
                workout_key='0:0:0',
            ).exists()
        )
        self.assertFalse(
            CompletedWorkout.objects.filter(
                plan=new_plan,
                workout_key='old:missing',
            ).exists()
        )
        self.assertTrue(new_plan.is_active)

    @patch('apps.plans.services.plan_service.generate_plan')
    def test_fatigue_feedback_reduces_volume_and_preserves_vdot(self, generate_plan):
        generate_plan.return_value = {
            'phases': [],
            'vdot': self.plan.snapshot_vdot,
            'adjustment_factor': 0.9,
        }

        response = self.client.post(
            reverse('plan_adjust', args=[self.plan.pk]),
            {'feedback': 'fatigued'},
        )

        self.plan.refresh_from_db()
        new_plan = GeneratedPlan.objects.get(user=self.user, is_active=True)
        self.assertFalse(self.plan.is_active)
        self.assertEqual(new_plan.adjustment_factor, 0.9)
        self.assertEqual(new_plan.snapshot_vdot, self.plan.snapshot_vdot)
        self.assertEqual(new_plan.goal_time_seconds, self.plan.goal_time_seconds)
        self.assertRedirects(response, reverse('plan_detail', args=[new_plan.pk]))
        generate_plan.assert_called_once_with(
            structure=self.template.structure,
            vdot=self.plan.snapshot_vdot,
            adjustment_factor=0.9,
        )

    @patch('apps.plans.services.plan_service.generate_plan')
    def test_easy_feedback_increases_volume(self, generate_plan):
        generate_plan.return_value = {
            'phases': [],
            'vdot': self.plan.snapshot_vdot,
            'adjustment_factor': 1.1,
        }

        response = self.client.post(
            reverse('plan_adjust', args=[self.plan.pk]),
            {'feedback': 'easy'},
        )

        new_plan = GeneratedPlan.objects.get(user=self.user, is_active=True)
        self.assertEqual(new_plan.adjustment_factor, 1.1)
        self.assertEqual(new_plan.snapshot_vdot, self.plan.snapshot_vdot)
        self.assertRedirects(response, reverse('plan_detail', args=[new_plan.pk]))
        generate_plan.assert_called_once_with(
            structure=self.template.structure,
            vdot=self.plan.snapshot_vdot,
            adjustment_factor=1.1,
        )

    def test_invalid_feedback_is_rejected_without_regeneration(self):
        response = self.client.post(
            reverse('plan_adjust', args=[self.plan.pk]),
            {'feedback': 'unknown'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(GeneratedPlan.objects.filter(user=self.user, is_active=True).count(), 1)

    def test_fatigue_feedback_respects_minimum_adjustment_factor(self):
        self.plan.adjustment_factor = 0.5
        self.plan.save(update_fields=['adjustment_factor'])

        response = self.client.post(
            reverse('plan_adjust', args=[self.plan.pk]),
            {'feedback': 'fatigued'},
        )

        self.assertRedirects(
            response,
            reverse('plan_detail', args=[self.plan.pk]),
            fetch_redirect_response=False,
        )
        self.plan.refresh_from_db()
        self.assertTrue(self.plan.is_active)
        self.assertEqual(
            GeneratedPlan.objects.filter(user=self.user, is_active=True).count(),
            1,
        )
        detail_response = self.client.get(reverse('plan_detail', args=[self.plan.pk]))
        self.assertContains(detail_response, 'Коэффициент нагрузки должен быть от')

    def test_completion_is_idempotent(self):
        url = reverse('workout_complete', args=[self.plan.pk])

        first_response = self.client.post(url, {'workout_key': '0:0:0'})
        second_response = self.client.post(url, {'workout_key': '0:0:0'})

        self.assertRedirects(first_response, reverse('plan_detail', args=[self.plan.pk]))
        self.assertRedirects(second_response, reverse('plan_detail', args=[self.plan.pk]))
        self.assertEqual(CompletedWorkout.objects.filter(plan=self.plan).count(), 1)

    def test_workout_cannot_be_completed_before_previous_workout(self):
        response = self.client.post(
            reverse('workout_complete', args=[self.plan.pk]),
            {'workout_key': '0:0:1'},
        )

        self.assertRedirects(response, reverse('plan_detail', args=[self.plan.pk]))
        self.assertFalse(
            CompletedWorkout.objects.filter(plan=self.plan, workout_key='0:0:1').exists()
        )

        self.client.post(
            reverse('workout_complete', args=[self.plan.pk]),
            {'workout_key': '0:0:0'},
        )
        next_response = self.client.post(
            reverse('workout_complete', args=[self.plan.pk]),
            {'workout_key': '0:0:1'},
        )
        self.assertRedirects(next_response, reverse('plan_detail', args=[self.plan.pk]))
        self.assertTrue(
            CompletedWorkout.objects.filter(plan=self.plan, workout_key='0:0:1').exists()
        )

    def test_invalid_workout_key_is_rejected(self):
        response = self.client.post(
            reverse('workout_complete', args=[self.plan.pk]),
            {'workout_key': 'not-in-this-plan'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(CompletedWorkout.objects.filter(plan=self.plan).count(), 0)

    def test_user_cannot_complete_workout_in_another_users_plan(self):
        other_user = User.objects.create_user(username='other-runner', password='SafeTestPass!2026')
        other_plan = GeneratedPlan.objects.create(
            user=other_user,
            snapshot_vdot=40,
            goal_race='10km',
            plan_data={'phases': []},
        )

        response = self.client.post(
            reverse('workout_complete', args=[other_plan.pk]),
            {'workout_key': '0:0:0'},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(CompletedWorkout.objects.count(), 0)

    def test_phase_one_block_can_be_completed_after_earlier_workouts(self):
        url = reverse('workout_complete', args=[self.plan.pk])
        phase_one_key = '0:1:phase'

        early_response = self.client.post(url, {'workout_key': phase_one_key})
        self.assertRedirects(early_response, reverse('plan_detail', args=[self.plan.pk]))
        self.assertFalse(
            CompletedWorkout.objects.filter(
                plan=self.plan,
                workout_key=phase_one_key,
            ).exists()
        )

        self.client.post(url, {'workout_key': '0:0:0'})
        self.client.post(url, {'workout_key': '0:0:1'})
        final_response = self.client.post(url, {'workout_key': phase_one_key})

        self.assertRedirects(final_response, reverse('plan_detail', args=[self.plan.pk]))
        self.plan.refresh_from_db()
        self.assertFalse(self.plan.is_active)
        self.assertEqual(CompletedWorkout.objects.filter(plan=self.plan).count(), 3)

    def test_plan_creation_page_redirects_while_active_plan_is_incomplete(self):
        response = self.client.get(reverse('plan_create'))

        self.assertRedirects(response, reverse('plan_detail', args=[self.plan.pk]))

    @patch('apps.plans.services.plan_service.calculate_vdot', return_value=40)
    @patch('apps.plans.services.plan_service.generate_plan', return_value={'phases': []})
    def test_service_rejects_second_plan_until_active_plan_is_completed(
        self,
        generate_plan,
        calculate_vdot,
    ):
        with self.assertRaises(PlanGenerationError):
            create_plan_for_user(
                user=self.user,
                race_type=self.race_type,
                goal_time_seconds=1500,
            )

        self.assertEqual(GeneratedPlan.objects.filter(user=self.user).count(), 1)
        self.assertTrue(self.plan.is_active)

    @patch('apps.plans.services.plan_service.calculate_vdot', return_value=40)
    @patch('apps.plans.services.plan_service.generate_plan', return_value={'phases': []})
    def test_service_allows_new_plan_after_all_items_are_completed(
        self,
        generate_plan,
        calculate_vdot,
    ):
        for workout_key in ('0:0:0', '0:0:1', '0:1:phase'):
            CompletedWorkout.objects.create(plan=self.plan, workout_key=workout_key)

        new_plan = create_plan_for_user(
            user=self.user,
            race_type=self.race_type,
            goal_time_seconds=1500,
        )

        self.plan.refresh_from_db()
        self.assertFalse(self.plan.is_active)
        self.assertTrue(new_plan.is_active)
        self.assertEqual(GeneratedPlan.objects.filter(user=self.user, is_active=True).count(), 1)

    def test_user_can_delete_own_plan(self):
        response = self.client.post(reverse('plan_delete', args=[self.plan.pk]))

        self.assertRedirects(response, reverse('plan_list'))
        self.assertFalse(GeneratedPlan.objects.filter(pk=self.plan.pk).exists())

    def test_user_cannot_delete_another_users_plan(self):
        other_user = User.objects.create_user(username='plan-owner', password='SafeTestPass!2026')
        other_plan = GeneratedPlan.objects.create(
            user=other_user,
            snapshot_vdot=40,
            goal_race='10km',
            plan_data={'phases': []},
        )

        response = self.client.post(reverse('plan_delete', args=[other_plan.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(GeneratedPlan.objects.filter(pk=other_plan.pk).exists())


class ReferenceDataCommandTests(TestCase):
    def test_seed_reference_data_is_idempotent(self):
        output = StringIO()

        call_command('seed_reference_data', skip_templates=True, stdout=output)
        call_command('seed_reference_data', skip_templates=True, stdout=output)

        self.assertEqual(RaceType.objects.count(), 6)
        self.assertEqual(VdotReference.objects.count(), 56)
        self.assertIn('Справочники загружены', output.getvalue())
