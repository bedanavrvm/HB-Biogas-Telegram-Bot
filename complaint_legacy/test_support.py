"""Synthetic Google boundary using the real Complaints projection and schema."""
from core.services.sheets import GoogleSheetsService
from core.services.sheet_schema import COMPLAINT_REGISTER_FIELD_HEADERS
from portal_legacy.test_support import Book


class ComplaintBook(Book):
    def __init__(self):
        super().__init__()
        self.register = self.add_worksheet('Complaints Register', 300, 22)
        self.register.cells[1] = list(COMPLAINT_REGISTER_FIELD_HEADERS.values())
        self.register.cells[2] = ['1', 'CMP-OLD-TEST', '', 'OPEN', 'OLD SYNTHETIC TEST']
        self.service_instance = GoogleSheetsService(sheet_id='synthetic-register', sheet_name=self.register.title,
                                                    sheet_schema={'schema_version': 2})
        self.service_instance._sheet = self.register
        self.service_instance._initialized = True
        self.register.batch_format = lambda _formats: None
        self.writes = []
        self.lose_next_publication_ack = False

    def batch_update(self, body):
        self.writes.append(body)
        result = super().batch_update(body)
        if self.lose_next_publication_ack and any(item.get('updateCells', {}).get('rows') for item in body['requests']):
            self.lose_next_publication_ack = False
            raise TimeoutError('Synthetic provider applied publication but lost acknowledgement')
        return result
