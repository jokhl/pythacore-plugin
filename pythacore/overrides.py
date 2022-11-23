import frappe
from frappe.model.naming import make_autoname, set_name_from_naming_options

# Doctypes
from erpnext.setup.doctype.item_group.item_group import ItemGroup
from frappe.contacts.doctype.address.address import Address
from erpnext.setup.doctype.territory.territory import Territory


class CustomItemGroup(ItemGroup):
    def autoname(self):
        autoname = frappe.get_meta(self.doctype).autoname or ''

        if not self.name and autoname:
            set_name_from_naming_options(autoname, self)
        else:
            super().autoname()


class CustomAddress(Address):
    def autoname(self):
        super().autoname()

        # Customer Delivery address name is: <Street Name> <No.> (<Customer Name>)
        if self.address_type == 'Shipping' and self.links[0].link_doctype == 'Customer':
            if self.city is not None:
                differentiator = self.city
            else:
                differentiator = self.links[0].link_title # customer name
            new_address = f"{self.address_line1} ({differentiator})"
            self.name = new_address
            self.address_title = new_address

        self.fs_code = make_autoname(self.naming_series, 'Address', self)


class CustomTerritory(Territory):
    def autoname(self):
        super().autoname()

        self.fs_code = make_autoname(self.naming_series, 'Territory', self)
