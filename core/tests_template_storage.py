from types import SimpleNamespace

from django.test import SimpleTestCase

from core.services.template_storage import GoogleDriveTemplateStorage


class _Request:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class _FilesResource:
    def __init__(self, existing):
        self.existing = existing
        self.list_calls = []
        self.update_calls = []
        self.create_calls = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return _Request({'files': self.existing})

    def update(self, **kwargs):
        self.update_calls.append(kwargs)
        return _Request({
            'id': kwargs['fileId'],
            'webViewLink': f"https://drive.test/{kwargs['fileId']}",
        })

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return _Request({'id': 'new-file', 'webViewLink': 'https://drive.test/new-file'})


class _DriveService:
    def __init__(self, files):
        self.resource = _FilesResource(files)

    def files(self):
        return self.resource


class GoogleDriveTemplateStorageTests(SimpleTestCase):
    def test_replaces_newest_same_name_and_trashes_older_duplicates(self):
        service = _DriveService([
            {'id': 'newest-template', 'name': 'template.xlsx', 'modifiedTime': '2026-07-27T10:00:00Z'},
            {'id': 'old-template', 'name': 'template.xlsx', 'modifiedTime': '2026-07-26T10:00:00Z'},
        ])
        storage = GoogleDriveTemplateStorage.__new__(GoogleDriveTemplateStorage)
        storage._media_storage = SimpleNamespace(service=service, parent_folder_id='root')
        storage._template_folder = lambda category: 'templates-requisition'

        file_id, url = storage.upload_template(
            b'latest workbook', filename='template.xlsx', category='Requisition',
        )

        self.assertEqual(file_id, 'newest-template')
        self.assertEqual(url, 'https://drive.test/newest-template')
        self.assertEqual(len(service.resource.create_calls), 0)
        self.assertEqual(len(service.resource.update_calls), 2)
        replacement = service.resource.update_calls[0]
        self.assertEqual(replacement['fileId'], 'newest-template')
        self.assertIn('latest upload', replacement['body']['description'])
        self.assertEqual(service.resource.update_calls[1]['fileId'], 'old-template')
        self.assertTrue(service.resource.update_calls[1]['body']['trashed'])

