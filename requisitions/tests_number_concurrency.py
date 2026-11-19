from concurrent.futures import ThreadPoolExecutor
from datetime import date
from hashlib import sha256
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from core.models import GroupSheetConfiguration
from requisitions.models import OrderSequenceState
from requisitions.services import claim_number, proposed_number, retain_finalized_requisition


class OrderNumberConcurrencyTests(TransactionTestCase):
    def test_independent_connections_cannot_allocate_the_same_number(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Requires PostgreSQL row locks.')
        actor = get_user_model().objects.create_user(username='synthetic-number-worker')
        group = GroupSheetConfiguration.objects.create(group_id='synthetic-number-concurrency', workflow={'type':'jawabu'})
        sequence = OrderSequenceState.objects.create(group_configuration=group, partner='HB', next_number=40)
        barrier = Barrier(2)

        def generate(worker):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                with transaction.atomic():
                    locked = OrderSequenceState.objects.select_for_update().get(pk=sequence.pk)
                    number = proposed_number(locked)
                    batch = retain_finalized_requisition(group_configuration_id=group.pk, fulfillment_partner='HB',
                        order_number=f'HB-{number}', finalized_at=timezone.now(), finalized_by_id=actor.pk,
                        filename='synthetic.xlsx', file_content=b'synthetic', content_checksum=sha256(b'synthetic').hexdigest(),
                        farmer_ids=[], requisition_date=date(2026,11,17))
                    claim_number(locked, batch, request_id=f'synthetic-worker-{worker}')
                    return number
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(generate, worker) for worker in range(2)]
            numbers = [job.result(timeout=20) for job in jobs]
        self.assertEqual(sorted(numbers), [40, 41])
