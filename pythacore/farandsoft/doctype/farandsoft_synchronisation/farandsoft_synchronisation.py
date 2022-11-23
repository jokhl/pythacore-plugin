# -*- coding: utf-8 -*-
# Copyright (c) 2019, Frappe Technologies and contributors
# For license information, please see license.txt

# System imports
import json
import traceback

# Frappe imports
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime
from frappe.utils.background_jobs import enqueue

# ERPNext imports
from erpnext.stock.get_item_details import apply_price_list

# Local imports
from pythacore.farandsoft.doctype.farandsoft_synchronisation.sync_job import SyncJob


class FarandsoftSynchronisation(Document):
    # We must manually set the name in order to have the time in it because
    # 'autoname' functionality of Frappe does not offer time patterns.
    # Reference: /frappe/model/naming.py
    def before_save(self):
        now = now_datetime()
        date = now.strftime('%d/%m/%Y')
        time = now.strftime('%H:%M')
        self.set_new_name(
            set_name=f"Synchronisation on {date} at {time}", force=True)
        self.sync_datetime = now

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
                event="farandsoft_sync",
                job_name=self.name,
                sync_doc_name=self.name,
                now=True,
            )
            return True

        return False


def start_sync_job(sync_doc_name):
    """This method runs in background job"""
    sync_doc = frappe.get_doc("Farandsoft Synchronisation", sync_doc_name)

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
            'farandsoft_sync_refresh',
            {'sync_doc_name': sync_doc.name}
        )


@frappe.whitelist()
def form_start_sync(sync_doc_name):
    return frappe.get_doc("Farandsoft Synchronisation", sync_doc_name).queue_sync_job()


@frappe.whitelist()
def set_status(sync_doc_name) -> None:
    results = json.loads(frappe.request.data)
    errors = results['errors']
    successes = results['successes']
    error_message = results['error_message']
    doc = frappe.get_doc('Farandsoft Synchronisation', sync_doc_name)

    if len(successes) > 0 and len(errors) > 0:
        frappe.db.set_value('Farandsoft Synchronisation',
                            sync_doc_name, 'status', 'Partial')
    elif len(errors) > 0:
        frappe.db.set_value('Farandsoft Synchronisation',
                            sync_doc_name, 'status', 'Error')
    elif doc.error_message is not None:
        frappe.db.set_value('Farandsoft Synchronisation',
                            sync_doc_name, 'status', 'Partial')
    else:
        frappe.db.set_value('Farandsoft Synchronisation',
                            sync_doc_name, 'status', 'Success')

    frappe.db.set_value('Farandsoft Synchronisation',
                        sync_doc_name, 'sync_log', json.dumps(errors + successes))

    if error_message is not None and error_message != '':
        frappe.db.set_value('Farandsoft Synchronisation',
                            sync_doc_name, 'status', 'Error')
        frappe.db.set_value('Farandsoft Synchronisation',
                            sync_doc_name, 'error_message', error_message)

    frappe.db.commit()

    frappe.publish_realtime(
        'farandsoft_sync_refresh',
        {'sync_doc_name': sync_doc_name}
    )

@frappe.whitelist()
def append_error(sync_doc_name, error_message) -> None:
    doc = frappe.get_doc('Farandsoft Synchronisation', sync_doc_name)

    error_message = error_message.replace("\n", '<br>')

    if doc.error_message is None:
        frappe.db.set_value('Farandsoft Synchronisation',
                            sync_doc_name, 'error_message', error_message)
    else:
        frappe.db.set_value('Farandsoft Synchronisation',
                            sync_doc_name, 'error_message', doc.error_message + "<br>" + error_message)

# We need a custom method in order to fetch linked docs such as the customer's addresses
@frappe.whitelist()
def get_all_customers(fields, filters, limit_page_length):
    customers = frappe.db.get_all('Customer', fields=fields, filters=filters, page_length=limit_page_length)

    for customer in customers:
        links = frappe.db.get_all('Dynamic Link', { 'link_doctype': 'Customer', 'link_name': customer['name'], 'parenttype': 'Address' }, ['parent'])
        
        if 'territory' in fields:
            customer['territory_fs_code'] = frappe.db.get_value('Territory', customer['territory'], 'fs_code')

        customer.addresses = []

        for link in links:
            address = frappe.db.get_value("Address", link['parent'], fieldname=['name', 'address_line1', 'address_line2', 'city', 'pincode', 'country', 'address_type', 'fs_code'], as_dict=True)
            address['customer'] = customer['name']
            customer.addresses.append(address)
    
    return customers

@frappe.whitelist()
def get_all_customer_addresses():
    links = frappe.db.get_all('Dynamic Link', { 'link_doctype': 'Customer', 'parenttype': 'Address' }, ['parent', 'link_name'])

    addresses = []

    for link in links:
        address = frappe.db.get_value("Address", link['parent'], fieldname=['name', 'address_line1', 'address_line2', 'city', 'pincode', 'country', 'address_type', 'fs_code'], as_dict=True)
        address['customer'] = link['link_name']
        addresses.append(address)

    return addresses

@frappe.whitelist()
def create_sales_order():
    data = json.loads(frappe.request.data)

    so = frappe.new_doc('Sales Order')
    args = frappe._dict(data)

    so.name = args.name
    so.customer = args.customer
    so.order_type = args.order_type
    so.transaction_date = args.transaction_date
    so.delivery_date = args.delivery_date
    so.fs_reference = args.fs_reference
    so.sales_partner = args.sales_partner
    so.shipping_address_name = args.shipping_address_name
    so.customer_address = args.customer_address

    customer_tax_cat = frappe.db.get_value('Customer', so.customer, 'tax_category')

    for item in args['items']:
        try:
            it = frappe.get_last_doc('Item Tax', filters={'parent': item['item_code'], 'tax_category': customer_tax_cat, 'scope': 'Sales'})

            if it is not None:
                item['item_tax_template'] = it.item_tax_template
        except:
            pass

        so.append('items', item)

    for tax in args['taxes']:
        so.append('taxes', tax)

    customer_price_list = frappe.db.get_value('Customer', so.customer, 'default_price_list')
    if customer_price_list is not None:
        so.selling_price_list = customer_price_list

    if so.sales_partner is not None:
        so.commission_rate = frappe.db.get_value('Sales Partner', so.sales_partner, 'commission_rate')
        so.calculate_commission()

    so.calculate_taxes_and_totals()
    so.insert()

    # We must update the item prices after inserting the new Sales Order then save because of
    # the `apply_price_list` method.
    if customer_price_list is not None:
        updated_so = apply_price_list(so.as_dict(), as_doc=True)
        so.delete_key('items')

        for item in updated_so.get('items'):
            item['rate'] = item['price_list_rate'] # we must manually update the item rate
            so.append('items', item)

        so.save()