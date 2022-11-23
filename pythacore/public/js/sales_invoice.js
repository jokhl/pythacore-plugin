frappe.ui.form.on('Sales Invoice', {
  refresh(frm) {
    if (frm.page.btn_secondary.text() === 'Cancel') {
      if (frm.doc.winbooks_sync_date) frm.page.btn_secondary.hide()
      else frm.page.btn_secondary.show()
    }
  }
})
