import json
from datetime import date
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
