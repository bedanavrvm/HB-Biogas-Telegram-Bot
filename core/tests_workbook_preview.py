import io

import openpyxl
from django.test import SimpleTestCase
from openpyxl.drawing.image import Image as WorkbookImage
from PIL import Image

from core.services.workbook_preview import serialize_workbook_preview


class WorkbookPrintPreviewTests(SimpleTestCase):
    def test_print_preview_crops_to_print_area_and_preserves_images(self):
        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet['A1'] = 'outside print area'
        worksheet['B2'] = 'inside print area'
        worksheet['D4'] = 'print area edge'
        worksheet.print_area = 'B2:D4'

        image_bytes = io.BytesIO()
        Image.new('RGB', (8, 8), 'red').save(image_bytes, format='PNG')
        image_bytes.seek(0)
        worksheet.add_image(WorkbookImage(image_bytes), 'B2')

        output = io.BytesIO()
        workbook.save(output)
        preview = serialize_workbook_preview(output.getvalue(), print_only=True)

        self.assertTrue(preview['print_only'])
        self.assertEqual(len(preview['sheets']), 1)
        sheet = preview['sheets'][0]
        self.assertEqual(len(sheet['rows']), 3)
        self.assertEqual(len(sheet['columns']), 3)
        self.assertEqual(sheet['rows'][0]['cells'][0]['value'], 'inside print area')
        self.assertNotIn('outside print area', str(sheet['rows']))
        self.assertEqual(sheet['images'][0]['row'], 1)
        self.assertEqual(sheet['images'][0]['column'], 1)
        self.assertTrue(sheet['images'][0]['data_url'].startswith('data:image/png;base64,'))
