from unittest.mock import Mock

from django.test import SimpleTestCase
from googleapiclient.http import HttpRequest
from httplib2 import Response

from core.services.order_approval import GoogleDriveMediaStorage


class DriveMediaDownloadTests(SimpleTestCase):
    def test_photos_avoid_small_sequential_ranges_and_keep_all_bytes(self):
        for size, expected_requests in [(2 * 1024 * 1024, 1), (9 * 1024 * 1024, 2)]:
            with self.subTest(size=size):
                content = b'x' * size
                ranges = []

                def receive(uri, method, headers, **kwargs):
                    start, end = map(int, headers['range'].removeprefix('bytes=').split('-'))
                    end = min(end, size - 1)
                    ranges.append((start, end))
                    return Response({'status': '206', 'content-range': f'bytes {start}-{end}/{size}'}), content[start:end + 1]

                http = Mock()
                http.request.side_effect = receive
                request = HttpRequest(http, lambda response, body: body, 'https://synthetic.test/evidence')
                storage = GoogleDriveMediaStorage(parent_folder_id='synthetic')
                storage._service = Mock()
                storage._service.files.return_value.get_media.return_value = request
                self.assertEqual(storage.download('synthetic-photo'), content)
                self.assertEqual(len(ranges), expected_requests)
