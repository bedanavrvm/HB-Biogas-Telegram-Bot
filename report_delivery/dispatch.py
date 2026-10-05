"""Best-effort immediate wake-up of durable, specifically requested deliveries.

The database owns work and leases. A process restart cannot discard a queued
report; reopening Settings or checking its status wakes eligible work again.
This is not a clock scheduler for unattended recurring reports.
"""
import logging
import time
from threading import BoundedSemaphore, Thread

from django.conf import settings
from django.db import close_old_connections, connections, transaction

from .services import claim_delivery, process_delivery

logger = logging.getLogger(__name__)
_slots = BoundedSemaphore(2)


def wake_deliveries(delivery_ids):
    ids = tuple(str(pk) for pk in delivery_ids)
    if not ids:
        return

    def launch():
        if not (settings.REPORT_EMAIL_DELIVERY_ENABLED and settings.RESEND_API_KEY and settings.REPORT_EMAIL_FROM):
            return
        if not _slots.acquire(blocking=False):
            return  # Durable work remains eligible for the next status check.

        def run():
            close_old_connections()
            try:
                # Each job is claimed once and all provider calls retain its
                # persisted idempotency key, including ambiguous retries.
                started = time.monotonic()
                for _ in range(min(50, len(ids))):
                    if time.monotonic() - started >= 50:
                        break
                    delivery = claim_delivery(delivery_ids=ids)
                    if delivery is None:
                        break
                    process_delivery(delivery)
            except Exception:
                logger.error('Immediate report delivery interrupted; durable work retained.')
            finally:
                connections.close_all()
                _slots.release()

        try:
            Thread(target=run, name='report-send-now', daemon=True).start()
        except Exception:
            _slots.release()
            logger.error('Immediate report delivery could not start; durable work retained.')

    transaction.on_commit(launch)
