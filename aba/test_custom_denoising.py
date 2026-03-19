import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase

from aba.models import SearchTerm
from aba import views


class CustomDenoisingTests(TestCase):
    databases = {'default', 'aba_db'}

    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()

    def _create_search_term(self, term, denoising=False):
        return SearchTerm.objects.using('aba_db').create(
            term=term,
            category='test',
            first_seen=date(2026, 1, 4),
            last_seen=date(2026, 1, 11),
            denoising=denoising,
            translation_cn='',
        )

    def test_normalize_custom_denoising_keywords(self):
        keywords = views._normalize_custom_denoising_keywords('  template  \nSVG Bundle\n\nsvg bundle\nTemplate\n')
        self.assertEqual(keywords, ['template', 'SVG Bundle'])

    def test_custom_denoising_whole_word_matching_helpers(self):
        patterns = views._build_custom_denoising_patterns(['eye', 'eye cream'])

        self.assertTrue(views._matches_custom_denoising_term('eye cream', patterns))
        self.assertTrue(views._matches_custom_denoising_term('best eye cream', patterns))
        self.assertFalse(views._matches_custom_denoising_term('eyebrow pencil', patterns))
        self.assertFalse(views._matches_custom_denoising_term('besteye cream', patterns))
        self.assertFalse(views._matches_custom_denoising_term('dey elastic', patterns))

    def test_apply_category_filter_uses_whole_word_matching(self):
        matching_term = self._create_search_term('eye cream')
        second_matching_term = self._create_search_term('best eye serum')
        embedded_term = self._create_search_term('eyebrow pencil')
        unrelated_term = self._create_search_term('dey elastic')

        filtered_ids = list(
            views._apply_category_filter(
                SearchTerm.objects.using('aba_db').order_by('id'),
                'eye',
                term_field='term',
            ).values_list('id', flat=True)
        )

        self.assertIn(matching_term.id, filtered_ids)
        self.assertIn(second_matching_term.id, filtered_ids)
        self.assertNotIn(embedded_term.id, filtered_ids)
        self.assertNotIn(unrelated_term.id, filtered_ids)

    def test_normalize_boolean_value_handles_false_string(self):
        self.assertFalse(views._normalize_boolean_value('false'))
        self.assertFalse(views._normalize_boolean_value('0'))
        self.assertTrue(views._normalize_boolean_value('true'))
        self.assertTrue(views._normalize_boolean_value('1'))

    def test_start_custom_denoising_rejects_blank_input(self):
        request = self.factory.post(
            '/api/custom-denoising/start/',
            data=json.dumps({'keywords_text': ' \n \n'}),
            content_type='application/json',
        )

        response = views.start_custom_denoising_api(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload['success'])
        self.assertIn('请输入至少一个有效的去噪词或词组', payload['error'])

    @patch('aba.views._launch_custom_denoising_task')
    def test_start_custom_denoising_returns_task_id(self, launch_mock):
        launch_mock.return_value = (
            'task-123',
            views._build_custom_denoising_progress(
                status='pending',
                processed_count=0,
                matched_count=0,
                updated_count=0,
                total_terms=10,
                keyword_count=1,
                message='任务已创建，准备开始处理',
                error='',
            )
        )
        request = self.factory.post(
            '/api/custom-denoising/start/',
            data=json.dumps({'keywords_text': ' template '}),
            content_type='application/json',
        )

        response = views.start_custom_denoising_api(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['success'])
        self.assertEqual(payload['data']['task_id'], 'task-123')
        launch_mock.assert_called_once_with(['template'])

    def test_run_custom_denoising_task_updates_matching_terms(self):
        matching_term_1 = self._create_search_term('Printable Template')
        matching_term_2 = self._create_search_term('SVG Bundle Pack')
        non_matching_term = self._create_search_term('Coffee Mug')
        task_id = 'task-run'

        cache.set(
            views._custom_denoising_cache_key(task_id),
            views._build_custom_denoising_progress(total_terms=3, keyword_count=2),
            views.CUSTOM_DENOISING_CACHE_TTL,
        )

        views._run_custom_denoising_task(task_id, ['template', 'svg bundle'], total_terms=3)
        progress = cache.get(views._custom_denoising_cache_key(task_id))

        self.assertEqual(progress['status'], 'success')
        self.assertEqual(progress['processed_count'], 3)
        self.assertEqual(progress['matched_count'], 2)
        self.assertEqual(progress['updated_count'], 2)
        self.assertIn('处理完成', progress['message'])

        matching_term_1.refresh_from_db(using='aba_db')
        matching_term_2.refresh_from_db(using='aba_db')
        non_matching_term.refresh_from_db(using='aba_db')
        self.assertTrue(matching_term_1.denoising)
        self.assertTrue(matching_term_2.denoising)
        self.assertFalse(non_matching_term.denoising)

    def test_run_custom_denoising_task_uses_whole_word_matching(self):
        exact_word_term = self._create_search_term('eye cream')
        phrase_term = self._create_search_term('best eye cream')
        embedded_term = self._create_search_term('eyebrow pencil')
        unrelated_term = self._create_search_term('dey elastic')
        task_id = 'task-whole-word'

        cache.set(
            views._custom_denoising_cache_key(task_id),
            views._build_custom_denoising_progress(total_terms=4, keyword_count=1),
            views.CUSTOM_DENOISING_CACHE_TTL,
        )

        views._run_custom_denoising_task(task_id, ['eye'], total_terms=4)

        exact_word_term.refresh_from_db(using='aba_db')
        phrase_term.refresh_from_db(using='aba_db')
        embedded_term.refresh_from_db(using='aba_db')
        unrelated_term.refresh_from_db(using='aba_db')

        self.assertTrue(exact_word_term.denoising)
        self.assertTrue(phrase_term.denoising)
        self.assertFalse(embedded_term.denoising)
        self.assertFalse(unrelated_term.denoising)

    def test_custom_denoising_progress_api_returns_progress_structure(self):
        task_id = 'task-progress'
        progress = views._build_custom_denoising_progress(
            status='running',
            processed_count=12,
            matched_count=3,
            updated_count=2,
            total_terms=50,
            keyword_count=2,
            message='目前已处理 12 条',
            error='',
        )
        cache.set(views._custom_denoising_cache_key(task_id), progress, views.CUSTOM_DENOISING_CACHE_TTL)

        request = self.factory.get('/api/custom-denoising/progress/', {'task_id': task_id})
        response = views.get_custom_denoising_progress_api(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['success'])
        self.assertEqual(payload['data']['status'], 'running')
        self.assertEqual(payload['data']['processed_count'], 12)
        self.assertEqual(payload['data']['matched_count'], 3)
        self.assertEqual(payload['data']['updated_count'], 2)
        self.assertEqual(payload['data']['total_terms'], 50)

    def test_new_words_window_defaults_to_13_weeks(self):
        window_end = date(2026, 3, 22)
        self.assertEqual(
            views._get_new_words_window_start(window_end),
            date(2025, 12, 28),
        )

    def test_build_new_words_row_uses_first_and_latest_metrics(self):
        search_term = self._create_search_term('hydrogen water', denoising=False)
        search_term.translation_cn = '氢水'
        search_term.first_seen = date(2026, 1, 4)

        first_metric = SimpleNamespace(
            id=11,
            report_week=date(2026, 1, 4),
            search_frequency_rank=120,
            asin_1_code='B001',
            asin_1_title='First Product',
            asin_1_click_share=Decimal('0.1200'),
            asin_1_conversion_share=Decimal('0.0300'),
            asin_2_code='B002',
            asin_2_title='Second Product',
            asin_2_click_share=Decimal('0.0500'),
            asin_2_conversion_share=Decimal('0.0200'),
            asin_3_code='B003',
            asin_3_title='Third Product',
            asin_3_click_share=Decimal('0.0200'),
            asin_3_conversion_share=Decimal('0.0100'),
        )
        latest_metric = SimpleNamespace(
            id=22,
            report_week=date(2026, 3, 22),
            search_frequency_rank=18,
            asin_1_code='B101',
            asin_1_title='Latest Product 1',
            asin_1_click_share=Decimal('0.3000'),
            asin_1_conversion_share=Decimal('0.1200'),
            asin_2_code='B102',
            asin_2_title='Latest Product 2',
            asin_2_click_share=Decimal('0.1500'),
            asin_2_conversion_share=Decimal('0.0800'),
            asin_3_code='B103',
            asin_3_title='Latest Product 3',
            asin_3_click_share=Decimal('0.0500'),
            asin_3_conversion_share=Decimal('0.0200'),
        )

        row = views._build_new_words_row(
            search_term,
            {
                'first_report_week': date(2026, 1, 4),
                'latest_report_week': date(2026, 3, 22),
                'appearance_count': 4,
                'window_start': date(2025, 12, 28),
                'window_end': date(2026, 3, 22),
            },
            [first_metric, latest_metric],
        )

        self.assertEqual(row['first_seen'], '2026-01-04')
        self.assertEqual(row['first_search_rank'], 120)
        self.assertEqual(row['latest_seen'], '2026-03-22')
        self.assertEqual(row['latest_search_rank'], 18)
        self.assertEqual(row['appearance_count'], 4)
        self.assertTrue(row['is_first_seen_in_window'])
        self.assertEqual(row['total_click_share'], 50.0)
        self.assertEqual(row['total_conversion_share'], 22.0)
        self.assertEqual(row['asin_1']['code'], 'B101')
        self.assertEqual(row['asin_2']['code'], 'B102')

    def test_get_new_words_api_requires_week(self):
        request = self.factory.get('/api/new-words/')
        response = views.get_aba_new_words_api(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['success'])
        self.assertTrue(payload['needs_week'])
        self.assertEqual(payload['data'], [])

    def test_get_new_words_api_rejects_reversed_range(self):
        request = self.factory.get('/api/new-words/', {
            'start_week': '2026-03-22',
            'end_week': '2026-01-04',
        })
        response = views.get_aba_new_words_api(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload['success'])
        self.assertIn('开始周期不能晚于结束周期', payload['error'])

    def test_build_new_words_row_counts_term_metrics_in_selected_window(self):
        search_term = self._create_search_term('term-a', denoising=False)
        search_term.first_seen = date(2026, 1, 11)
        search_term.translation_cn = '词A'

        metric_1 = SimpleNamespace(
            id=1,
            report_week=date(2026, 1, 11),
            search_frequency_rank=99,
            asin_1_code='B201',
            asin_1_title='P1',
            asin_1_click_share=Decimal('0.1000'),
            asin_1_conversion_share=Decimal('0.0200'),
            asin_2_code='',
            asin_2_title='',
            asin_2_click_share=None,
            asin_2_conversion_share=None,
            asin_3_code='',
            asin_3_title='',
            asin_3_click_share=None,
            asin_3_conversion_share=None,
        )
        metric_2 = SimpleNamespace(
            id=2,
            report_week=date(2026, 1, 18),
            search_frequency_rank=88,
            asin_1_code='B202',
            asin_1_title='P2',
            asin_1_click_share=Decimal('0.2000'),
            asin_1_conversion_share=Decimal('0.0400'),
            asin_2_code='',
            asin_2_title='',
            asin_2_click_share=None,
            asin_2_conversion_share=None,
            asin_3_code='',
            asin_3_title='',
            asin_3_click_share=None,
            asin_3_conversion_share=None,
        )

        row = views._build_new_words_row(
            search_term,
            {
                'first_report_week': date(2026, 1, 11),
                'latest_report_week': date(2026, 1, 18),
                'appearance_count': 2,
                'window_start': date(2026, 1, 4),
                'window_end': date(2026, 1, 25),
            },
            [metric_1, metric_2],
        )

        self.assertEqual(row['first_seen'], '2026-01-11')
        self.assertEqual(row['appearance_count'], 2)
        self.assertTrue(row['is_first_seen_in_window'])
        self.assertEqual(row['latest_seen'], '2026-01-18')

    def test_calculate_rank_growth_percent_uses_percentage_improvement(self):
        self.assertEqual(views._calculate_rank_growth_percent(30, 100), 70.0)
        self.assertEqual(views._calculate_rank_growth_percent(50, 100), 50.0)
        self.assertEqual(views._calculate_rank_growth_percent(90, 100), 10.0)
        self.assertIsNone(views._calculate_rank_growth_percent(30, 0))

    def test_is_continuous_growth_requires_four_strictly_improving_points(self):
        self.assertTrue(views._is_continuous_growth([120, 90, 50, 20]))
        self.assertFalse(views._is_continuous_growth([120, 90, 90, 20]))
        self.assertFalse(views._is_continuous_growth([120, 90, 50]))

    def test_get_hot_word_categories_matches_updated_word_define(self):
        metric = SimpleNamespace(
            search_frequency_rank=35000,
            last_week_rank=100000,
            asin_1_click_share=Decimal('0.5000'),
            asin_1_conversion_share=Decimal('0.0000'),
            asin_2_click_share=Decimal('0.2500'),
            asin_2_conversion_share=Decimal('0.0000'),
            asin_3_click_share=Decimal('0.0500'),
            asin_3_conversion_share=Decimal('0.0000'),
        )
        trend_rows = [
            {'week': '2026-02-16', 'rank': 120000},
            {'week': '2026-02-23', 'rank': 90000},
            {'week': '2026-03-02', 'rank': 60000},
            {'week': '2026-03-09', 'rank': 35000},
        ]

        categories = views._get_hot_word_categories(metric, trend_rows)

        self.assertIn('持续增长词', categories)
        self.assertIn('黄金词', categories)
        self.assertIn('竞争词', categories)
        self.assertIn('捡漏词', categories)
        self.assertIn('爆发词', categories)
        self.assertIn('飙升词', categories)
        self.assertIn('潜力词', categories)
