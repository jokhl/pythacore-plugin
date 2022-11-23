from __future__ import unicode_literals

# System imports
import redis
import json
from decimal import Decimal

# Local imports
import frappe
from datetime import datetime, date
from frappe import _
from erpnext.controllers.taxes_and_totals import get_itemised_tax_breakup_data

# How many steps do we have at initialization? Used for progress tracking.
# - Init sync
# - Sync with Winbooks
INITIAL_STEPS = 2

# How many steps do we have per doctype? Used for progress tracking.
# - Fetch from ERP
# - Write to import file
DOCTYPE_STEPS = 2

class SyncJob:
    def __init__(self, sync_doc, console=False):
        self.sync_doc = sync_doc
        self.console = console
        self.listeners = {}
        self.documents = []
        self.redis = redis.Redis.from_url('redis://127.0.0.1:13000')
        self.purchase_invoices = { 'count': 0, 'range': '' }
        self.sales_invoices = { 'count': 0, 'range': '' }
        self.customers = { 'count': 0, 'range': '' }
        self.suppliers = { 'count': 0, 'range': '' }
        self.progress_total = INITIAL_STEPS

    def sync(self):
        if self.sync_doc.sync_customers and not self.sync_doc.sync_sales_invoices:
            self.progress_total += 2 * DOCTYPE_STEPS
        elif self.sync_doc.sync_customers:
            self.progress_total += 1 * DOCTYPE_STEPS
        
        if self.sync_doc.sync_suppliers and not self.sync_doc.sync_purchase_invoices:
            self.progress_total += 2 * DOCTYPE_STEPS
        elif self.sync_doc.sync_suppliers:
            self.progress_total += 1 * DOCTYPE_STEPS
        
        if self.sync_doc.sync_sales_invoices:
            self.progress_total += 1 * DOCTYPE_STEPS
        if self.sync_doc.sync_purchase_invoices:
            self.progress_total += 1 * DOCTYPE_STEPS

        self.set_status('In Progress')
        self.init_progress()
        self.update_progress(message='Starting synchronisation...')

        frappe.publish_realtime(
            event='start_sync',
            message={
                'winbooks_sync': self.sync_doc.name,
                'sync_si_up_to': self.sync_doc.sync_si_up_to,
                'sync_pi_up_to': self.sync_doc.sync_pi_up_to,
                'sync_customers': self.sync_doc.sync_customers,
                'sync_suppliers': self.sync_doc.sync_suppliers,
                'sync_sales_invoices': self.sync_doc.sync_sales_invoices,
                'sync_purchase_invoices': self.sync_doc.sync_purchase_invoices
            },
            room='pythacore:winbooks'
        )

    def refresh_form(self) -> None:
        frappe.publish_realtime(
            'winbooks_sync_refresh',
            { 'winbooks_sync': self.sync_doc.name }
        )

    def init_progress(self) -> None:
        self.cache_progress(0, self.progress_total)

    # We convert the integer params to strings so that we can easily decode them
    # when we will fetch them because redis stores data in binary format.
    def cache_progress(self, current: int, total: int = None) -> None:
        print(f"Caching progress current {current} total {total}")
        self.redis.hset(
            self.sync_doc.name,
            'progress_current',
            str(current)
        )

        if total is not None:
            self.redis.hset(
                self.sync_doc.name,
                'progress_total',
                str(total)
            )

    def update_progress(self, step: int = 1, message: str = '') -> None:
        total = self.redis.hget(
            self.sync_doc.name,
            'progress_total'
        )
        current = self.redis.hget(
            self.sync_doc.name,
            'progress_current'
        )

        total = int(total)
        current = int(current)
        current += step

        self.cache_progress(current)

        frappe.publish_realtime(
            event='winbooks_sync_progress',
            message={
                'winbooks_sync': self.sync_doc.name,
                'current': current,
                'total': total,
                'message': message
            }
        )

    def set_status(self, status) -> None:
        self.sync_doc.db_set('status', status)

    def set_headline(self, headline) -> None:
        self.sync_doc.db_set('headline', headline)

def create_sync_log_line(document):
    return {
        'doctype': document['doctype'],
        'name': document['name'],
        'status': 'Pending'
    }

def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError ("Type %s not serializable" % type(obj))
