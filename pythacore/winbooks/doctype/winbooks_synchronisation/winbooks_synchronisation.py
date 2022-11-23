# -*- coding: utf-8 -*-
# Copyright (c) 2019, Frappe Technologies and contributors
# For license information, please see license.txt

# System imports
import json
import traceback
from decimal import Decimal

# Frappe imports
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, flt
from frappe.utils.background_jobs import enqueue

# Local imports
from pythacore.winbooks.doctype.winbooks_synchronisation.sync_job import SyncJob


class WinbooksSynchronisation(Document):
    # We must manually set the name in order to have the time in it because
    # 'autoname' functionality of Frappe does not offer time patterns.
    # Reference: /frappe/model/naming.py
    def before_save(self):
        now = now_datetime()
        date = now.strftime('%d/%m/%Y')
        time = now.strftime('%H:%M')
        self.set_new_name(
            set_name=f"Synchronisation on {date} at {time}", force=True)
        self.sync_date = now

    def queue_sync_job(self):
        from frappe.core.page.background_jobs.background_jobs import get_info
        from frappe.utils.scheduler import is_scheduler_inactive

        pythacore_online = frappe.cache().get('pythacore_online')

        if is_scheduler_inactive() and not frappe.flags.in_test:
            frappe.throw(
                _("Scheduler is inactive. Cannot start synchronisation."), title=_("Scheduler Inactive")
            )

        if pythacore_online is None:
            frappe.throw(
                _("Could not connect to PythaCore. Cannot start synchronisation."), title=_("PythaCore Offline")
            )

        enqueued_jobs = [d.get("job_name") for d in get_info()]

        if self.name not in enqueued_jobs:
            enqueue(
                start_sync_job,
                queue="default",
                timeout=6000,
                event="winbooks_sync",
                job_name=self.name,
                sync_doc_name=self.name,
                now=frappe.conf.developer_mode or frappe.flags.in_test,
            )
            return True

        return False


def start_sync_job(sync_doc_name):
    """This method runs in background job"""
    sync_doc = frappe.get_doc("Winbooks Synchronisation", sync_doc_name)

    if sync_doc.status == 'Error':
        sync_doc.db_set('error_message', None)

    try:
        worker = SyncJob(sync_doc)
        worker.sync()
    except Exception as e:
        frappe.db.rollback()
        sync_doc.db_set("status", "Error")
        sync_doc.db_set('error_message', e)
        print(traceback.print_exc())
        frappe.log_error(frappe.get_traceback())
        frappe.publish_realtime(
            'winbooks_sync_refresh',
            {'winbooks_sync': sync_doc.name}
        )


def set_headline(self, headline) -> None:
    self.sync_doc.db_set('headline', headline)


def get_warning_message(code, data):
    if code == 'ACC_MOD':
        return _('The data of {0} {1} has been updated in Winbooks.').format(data['doctype'], data['docname'])
    elif code == 'SEQ_RUPT':
        return _('The reference of this document breaks the sequence. The last reference before this document in Winbooks is: <u>{0}</u>').format(data['doc_before'])
    elif code == 'OUT_DAT':
        return _('The date of this document is out of the accounting period in Winbooks. The accounting period is <u>{0}</u> and the date of this document is <u>{1}</u>').format(data['period'], data['date'])


def get_error_message(code, data):
    if code == 'INV_STATUS':
        return _('Cannot synchronise {0} <u>{1}</u> because it has status <u>{2}</u>.').format(data['doctype'], data['docname'], data['status'])


def set_ranges(sync_doc_name, docs):
    if docs is None:
        frappe.db.set_value('Winbooks Synchronisation',
                            sync_doc_name, 'customers', _('Nothing'))
        frappe.db.set_value('Winbooks Synchronisation',
                            sync_doc_name, 'suppliers', _('Nothing'))
        frappe.db.set_value('Winbooks Synchronisation',
                            sync_doc_name, 'sales_invoices', _('Nothing'))
        frappe.db.set_value('Winbooks Synchronisation',
                            sync_doc_name, 'purchase_invoices', _('Nothing'))
    else:
        frappe.db.set_value('Winbooks Synchronisation',
                            sync_doc_name, 'status', 'Error')

    frappe.db.commit()


@frappe.whitelist()
def form_start_sync(sync_doc_name):
    return frappe.get_doc("Winbooks Synchronisation", sync_doc_name).queue_sync_job()


@frappe.whitelist()
def abort(sync_doc_name) -> None:
    results = json.loads(frappe.request.data)

    frappe.db.set_value('Winbooks Synchronisation',
                        sync_doc_name, 'status', 'Error')
    set_ranges(sync_doc_name, None)

    for doc in results['docs']:
        if 'status' not in doc:
            doc['status'] = 'Error'
        elif len(doc['warning_codes']) > 0:
            doc['message'] = ''

            for idx, warning_code in enumerate(doc['warning_codes']):
                if idx > 0:
                    doc['message'] += '<br>'

                doc['message'] += f"- {get_warning_message(warning_code, doc['warning_data'])}"

    message = ''

    if results['reason']['type'] == 'fatal_warning':
        message += '<b>'
        message += _('Sorry, there is at least one problem that could not be solved automatically (see below for details).')
        message += '</b><br><br>'

        if 'message' in results['reason']:
            message += results['reason']['message']
            message += '<br><br>'

        message += '<b>'
        message += _('The data was <u>NOT</u> imported into Winbooks.')
        message += '</b>'
        frappe.db.set_value('Winbooks Synchronisation',
                            sync_doc_name, 'warning_message', message)
    else:
        message += '<b>'
        message += _('Sorry, there is at least one fatal error.')
        message += '</b><br><br>'

        if 'message' in results['reason']:
            message += results['reason']['message']
            message += '<br><br>'
        elif 'error_code' in results['reason']:
            message += get_error_message(results['reason']
                                         ['error_code'], results['reason']['error_data'])
            message += '<br><br>'

        message += '<b>'
        message += _('The data was <u>NOT</u> imported into Winbooks.')
        message += '</b>'
        frappe.db.set_value('Winbooks Synchronisation',
                            sync_doc_name, 'error_message', message)

    frappe.db.set_value('Winbooks Synchronisation',
                        sync_doc_name, 'sync_log', json.dumps(results['docs']))
    frappe.db.commit()

    frappe.publish_realtime(
        'winbooks_sync_refresh',
        {'sync_doc_name': sync_doc_name}
    )


@frappe.whitelist()
def set_success(sync_doc_name) -> None:
    results = json.loads(frappe.request.data)
    warnings_presence = False

    frappe.db.set_value('Winbooks Synchronisation',
                        sync_doc_name, 'status', 'Success')
    sync_date = frappe.db.get_value(
        'Winbooks Synchronisation', sync_doc_name, 'sync_date')

    for doc in results['docs']:
        frappe.db.set_value(doc['doctype'], doc['name'],
                            'winbooks_sync_date', sync_date)

        if 'status' not in doc:
            # PythaCore might have set the status to 'Warning'. If no status is set, we set it manually here.
            doc['status'] = 'Success'
        elif doc['status'] == 'Warning':
            warnings_presence = True
            doc['message'] = ''

            for idx, warning_code in enumerate(doc['warning_codes']):
                if idx > 0:
                    doc['message'] += '<br>'

                doc['message'] += f"- {get_warning_message(warning_code, doc['warning_data'])}"

    # If one or more docs have warning status, show a warning card at the top of the sync page.
    if warnings_presence:
        new_message = _(
            "Winbooks gave at least one warning but don't worry, <b>it was taken care of automatically</b> (see below for details).")

        if 'warning_message' in doc and doc.warning_message is not None:
            new_message = doc.warning_message + "<br>" + new_message

        frappe.db.set_value('Winbooks Synchronisation',
                            sync_doc_name, 'warning_message', new_message)

    if len(results['docs']) == 0:
        frappe.db.set_value('Winbooks Synchronisation', sync_doc_name,
                            'headline', _('Nothing to synchronise.'))

    frappe.db.set_value('Winbooks Synchronisation',
                        sync_doc_name, 'sync_log', json.dumps(results['docs']))
    frappe.db.commit()

    frappe.publish_realtime('winbooks_sync_refresh', {
                            'sync_doc_name': sync_doc_name})


@frappe.whitelist()
def get_invoices(doctype, fields, filters, limit_page_length, order_by):
    invoices = frappe.db.get_all(
        doctype, fields=fields, filters=filters, page_length=limit_page_length, order_by=order_by)

    for invoice in invoices:
        doc = frappe.get_doc(doctype, invoice['name'])

        # We created a new method in order to use the `vat_data` field of Sales/Purchase Invoice.
        # This field is calculated and set upon saving the invoice so there is no need to redo
        # all the calculations here. Nonetheless, we are keeping the 'old way' method for
        # backwards compatibility.
        if doctype in ['Sales Invoice', 'Purchase Invoice'] and doc.vat_data is not None:
            vat_data = json.loads(doc.vat_data)
            total_vat = vat_data['total_vat_amount']
            vat_breakup = vat_data['vat_code_breakup']
        else:
            total_vat, vat_breakup = old_get_vat(doc)

        invoice['vat_amount'] = total_vat
        invoice['vat_breakup'] = vat_breakup

    return invoices

# Keep this for backwards compatibility.
def old_get_vat(doc):
    vat_breakup = {}
    total_vat_amount = 0

    for tax in doc.taxes:
        if tax.tax_type == 'VAT':
            item_tax_map = json.loads(
                tax.item_wise_tax_detail) if tax.item_wise_tax_detail else {}

            for _, tax_data in item_tax_map.items():
                if isinstance(tax_data, list) and len(tax_data) == 4:
                    vat_rate = tax_data[0]
                    vat_amount = tax_data[1]
                    vat_base = tax_data[2]
                    vat_code = tax_data[3]

                    if vat_code in vat_breakup:
                        vat_breakup[vat_code]['vat_amount'] += vat_amount
                        vat_breakup[vat_code]['vat_base'] += vat_base
                    else:
                        vat_breakup[vat_code] = {
                            'vat_rate': vat_rate,
                            'vat_amount': vat_amount,
                            'vat_base': vat_base
                        }
                else:
                    continue

    # We need to round VAT subtotals in order to be accurate.
    for vat in vat_breakup:
        vat_breakup[vat]['vat_amount'] = flt(vat_breakup[vat]['vat_amount'], 2)
        vat_breakup[vat]['vat_base'] = flt(vat_breakup[vat]['vat_base'], 2)
        total_vat_amount += flt(vat_breakup[vat]['vat_amount'], 2)

    return total_vat_amount, vat_breakup

# We need a custom method in order to fetch linked docs such as the customer's addresses


@frappe.whitelist()
def get_all_customers(fields, filters, limit_page_length):
    customers = frappe.db.get_all(
        'Customer', fields=fields, filters=filters, page_length=limit_page_length)

    for customer in customers:
        links = frappe.db.get_all('Dynamic Link', {
                                  'link_doctype': 'Customer', 'link_name': customer['name'], 'parenttype': 'Address'}, ['parent'])
        customer.addresses = []

        for link in links:
            address = frappe.db.get_value("Address", link['parent'], fieldname=[
                                          'name', 'address_line1', 'address_line2', 'city', 'pincode', 'country', 'address_type', 'fs_code'], as_dict=True)
            address['customer'] = customer['name']
            customer.addresses.append(address)

        links = frappe.db.get_all('Dynamic Link', {
                                  'link_doctype': 'Customer', 'link_name': customer['name'], 'parenttype': 'Contact'}, ['parent'])
        customer.contacts = []

        for link in links:
            contact = frappe.db.get_value("Contact", link['parent'], fieldname=[
                                          'first_name', 'last_name', 'email_id', 'phone', 'is_primary_contact'], as_dict=True)
            contact['customer'] = customer['name']

            for part in contact:
                if contact[part] is None:
                    contact[part] = ''

            customer.contacts.append(contact)

    return customers

# We need a custom method in order to fetch linked docs such as the supplier's addresses


@frappe.whitelist()
def get_all_suppliers(fields, filters, limit_page_length):
    suppliers = frappe.db.get_all(
        'Supplier', fields=fields, filters=filters, page_length=limit_page_length)

    for supplier in suppliers:
        links = frappe.db.get_all('Dynamic Link', {
                                  'link_doctype': 'Supplier', 'link_name': supplier['name'], 'parenttype': 'Address'}, ['parent'])
        supplier.addresses = []

        for link in links:
            address = frappe.db.get_value("Address", link['parent'], fieldname=[
                                          'name', 'address_line1', 'address_line2', 'city', 'pincode', 'country', 'address_type', 'fs_code'], as_dict=True)
            address['supplier'] = supplier['name']

            for part in address:
                if address[part] is None:
                    address[part] = ''

            supplier.addresses.append(address)

        links = frappe.db.get_all('Dynamic Link', {
                                  'link_doctype': 'Supplier', 'link_name': supplier['name'], 'parenttype': 'Contact'}, ['parent'])
        supplier.contacts = []

        for link in links:
            contact = frappe.db.get_value("Contact", link['parent'], fieldname=[
                                          'first_name', 'last_name', 'email_id', 'phone', 'is_primary_contact'], as_dict=True)
            contact['supplier'] = supplier['name']

            for part in contact:
                if contact[part] is None:
                    contact[part] = ''

            supplier.contacts.append(contact)

    return suppliers
