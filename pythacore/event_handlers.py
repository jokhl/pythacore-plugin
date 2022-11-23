import frappe
from frappe import _


def before_cancel(doc, method=None):
    if doc.winbooks_sync_date is not None:
        frappe.throw(
            title='Error',
            msg=_(
                "Sorry, you can't cancel an invoice which is already synced with Winbooks.")
        )
