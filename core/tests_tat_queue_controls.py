import inspect
import json
from unittest.mock import patch

from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase

from core.api.views import tat_tracker_home, tat_tracker_home_fragment


class TatQueueCapabilityTests(SimpleTestCase):
    def test_search_requires_its_own_capability_on_both_home_endpoints(self):
        for view in [tat_tracker_home, tat_tracker_home_fragment]:
            with self.subTest(view=view.__name__):
                request = RequestFactory().post('/synthetic-home/', json.dumps({'query': 'Synthetic'}),
                                                content_type='application/json')
                def capability(_user, key, _group):
                    return JsonResponse({'ok': False}, status=403) if key == 'tat.case.search' else None
                with patch('core.api.views._tat_context', return_value=('-synthetic', object(), {}, {}, None)), \
                     patch('core.api.views._tat_capability_error', side_effect=capability) as check, \
                     patch('core.services.tat_tracker.home_data') as home:
                    response = inspect.unwrap(view)(request)
                self.assertEqual(response.status_code, 403)
                self.assertEqual([call.args[1] for call in check.call_args_list], ['tat.home.view', 'tat.case.search'])
                home.assert_not_called()

    def test_normal_queue_does_not_require_search_capability(self):
        request = RequestFactory().post('/synthetic-home/', json.dumps({'query': '   '}),
                                        content_type='application/json')
        with patch('core.api.views._tat_context', return_value=('-synthetic', object(), {}, {}, None)), \
             patch('core.api.views._tat_capability_error', return_value=None) as check, \
             patch('core.services.tat_tracker.home_data', return_value={'items': []}):
            response = inspect.unwrap(tat_tracker_home)(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([call.args[1] for call in check.call_args_list], ['tat.home.view'])
