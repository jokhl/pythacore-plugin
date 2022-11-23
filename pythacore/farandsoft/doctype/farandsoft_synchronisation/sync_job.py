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


class SyncJob:
    def __init__(self, sync_doc, console=False):
        self.sync_doc = sync_doc
        self.console = console
        self.listeners = {}
        self.documents = []
        self.redis = redis.Redis.from_url('redis://127.0.0.1:13000')
        self.purchase_invoices = {'count': 0, 'range': ''}
        self.sales_invoices = {'count': 0, 'range': ''}
        self.customers = {'count': 0, 'range': ''}
        self.suppliers = {'count': 0, 'range': ''}

    def sync(self):
        self.set_status('In Progress')
        self.init_progress()
        self.send_start_sync()

    def send_start_sync(self) -> None:
        frappe.publish_realtime(
            event='start_sync',
            message={
                'sync_doc_name': self.sync_doc.name,
                'sync_customers': self.sync_doc.sync_customers,
                'sync_sales_orders': self.sync_doc.sync_sales_orders,
                'sync_items': self.sync_doc.sync_items,
                'sync_from_date': self.sync_doc.sync_from_date
            },
            room='pythacore:farandsoft'
        )
        self.update_progress(message='Starting synchronisation...')

    def refresh_form(self) -> None:
        frappe.publish_realtime(
            'farandsoft_sync_refresh',
            {'sync_doc_name': self.sync_doc.name}
        )

    def init_progress(self) -> None:
        self.cache_progress(0, 0)

    # We convert the integer params to strings so that we can easily decode them
    # when we will fetch them because redis stores data in binary format.
    def cache_progress(self, current: int, total: int = None) -> None:
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
            event='farandsoft_sync_progress',
            message={
                'sync_doc_name': self.sync_doc.name,
                'current': current,
                'total': total,
                'message': message
            }
        )

    def set_status(self, status) -> None:
        self.sync_doc.db_set('status', status)

    def set_headline(self, headline) -> None:
        self.sync_doc.db_set('headline', headline)

    def fetch_documents(self, doctype) -> dict:
        doc_list = frappe.get_all(
            doctype,
            fields=get_fields_for(doctype),
            filters=get_filters_for(doctype)
        )

        for doc_info in doc_list:
            doc_info['doctype'] = doctype

            if doctype == 'Sales Invoice' or doctype == 'Purchase Invoice':
                doc = frappe.get_doc(doctype, doc_info['name'])
                total_vat, vat_breakup = get_vat(doc)
                doc_info['vat_amount'] = total_vat
                doc_info['vat_breakup'] = vat_breakup

        return doc_list if len(doc_list) > 0 else None


def get_fields_for(doctype):
    if doctype == 'Sales Invoice':
        return SALES_INVOICE_FIELDS
    elif doctype == 'Purchase Invoice':
        return PURCHASE_INVOICE_FIELDS
    elif doctype == 'Customer':
        return CUSTOMER_FIELDS
    elif doctype == 'Supplier':
        return SUPPLIER_FIELDS


def get_filters_for(doctype):
    if 'Invoice' in doctype:
        return [
            ['status', '!=', 'Cancelled'],
            ['status', '!=', 'Draft'],
            ['winbooks_sync_date', 'is', 'not set']
        ]
    else:
        return [
            ['disabled', '=', '0'],
            ['winbooks_sync_date', 'is', 'not set']
        ]


def get_vat(doc):
    itemised_taxes = get_itemised_tax_breakup_data(doc)

    breakup = itemised_taxes[0]
    vat_breakup = {}
    total_vat = Decimal(0)

    for item in breakup:
        item_taxes = breakup[item]
        for tax_name in item_taxes:
            # TODO Change this is account head is named differently.
            if tax_name.startswith('VAT'):
                vat_code = str(int(item_taxes[tax_name]['tax_rate']))
                vat_amount = Decimal(item_taxes[tax_name]['tax_amount'])
                total_vat += vat_amount
                if vat_code in vat_breakup:
                    vat_breakup[vat_code] += vat_amount
                else:
                    vat_breakup[vat_code] = vat_amount

    return total_vat, vat_breakup


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
    raise TypeError("Type %s not serializable" % type(obj))
