function get_indicator_dot(doc) {
  let color, title

  if (doc.winbooks_sync_date) {
    color = 'text-success'
    title = 'Synced'
  } else {
    color = 'text-black-50'
    title = 'Not Synced'
  }

  return `<i class='fa fa-exchange ${color}' title='${__(title)}'></i>`
}

function get_form_link(doc) {
  if (frappe.listview_settings['Sales Invoice'].get_form_link) {
    return frappe.listview_settings['Sales Invoice'].get_form_link(doc)
  }

  const docname = doc.name.match(/[%'"#\s]/)
    ? encodeURIComponent(doc.name)
    : doc.name

  return `/app/${frappe.router.slug(
    frappe.router.doctype_layout || 'Sales Invoice'
  )}/${docname}`
}

function new_get_header_html() {
  if (!this.columns) {
    return
  }

  const subject_field = this.columns[0].df
  let subject_html = `
    <input class="level-item list-check-all" type="checkbox"
      title="${__('Select All')}">
    <span class="level-item">${__(subject_field.label)}</span>
  `
  const $columns = this.columns
    .map((col) => {
      console.log(col)
      let classes = [
        'list-row-col ellipsis',
        col.type == 'Subject' ? 'list-subject level' : 'hidden-xs',
        col.type == 'Tag' ? 'tag-col hide' : '',
        frappe.model.is_numeric_field(col.df) ? 'text-right' : '',
      ].join(' ')

      return `
      <div class="${classes}">
        ${col.type === 'Subject'
          ? subject_html
          : `
          <span>${__((col.df && col.df.label) || col.type)}</span>`
        }
      </div>
    `
    })
    .join('')

  return this.get_header_html_skeleton(
    $columns,
    '<span class="list-count"></span>'
  )
}

// We must copy the contents of `erpnext/accounts/doctype/sales_invoice/sales_invoice_list.js` here
// because we are overriding frappe.listview_settings['Sales Invoice'] in this file in order to add
// our customizations.
frappe.listview_settings['Sales Invoice'] = {
  // COPIED FROM ERPNEXT
  get_indicator: function (doc) {
    const status_colors = {
      "Draft": "grey",
      "Unpaid": "orange",
      "Paid": "green",
      "Return": "gray",
      "Credit Note Issued": "gray",
      "Unpaid and Discounted": "orange",
      "Partly Paid and Discounted": "yellow",
      "Overdue and Discounted": "red",
      "Overdue": "red",
      "Partly Paid": "yellow",
      "Internal Transfer": "darkgrey"
    };
    return [__(doc.status), status_colors[doc.status], "status,=," + doc.status];
  },
  right_column: "grand_total",
  // CUSTOMIZATIONS BELOW
  hide_name_column: true,
  add_fields: ['customer', 'customer_name', 'base_grand_total', 'outstanding_amount', 'due_date', 'company',
    'currency', 'is_return', 'winbooks_sync_date'],
  formatters: {
    name: function (value, df, doc) {
      const escaped_subject = frappe.utils.escape_html(value)
      let subject_html = `
        <span class="level-item select-like">
          <input class="list-row-checkbox" type="checkbox"
            data-name="${escape(doc.name)}">
          <span class="list-row-like hidden-xs style="margin-bottom: 1px;">
            ${get_indicator_dot(doc)}
          </span>
        </span>
        <span class="level-item bold ellipsis" title="${escaped_subject}">
          <a class="ellipsis"
            href="${get_form_link(doc)}"
            title="${escaped_subject}"
            data-doctype="Sales Invoice"
            data-name="${doc.name}">
            ${strip_html(value.toString())}
          </a>
        </span>
      `

      return subject_html
    },
  },
  onload: function (listView) {
    // Set Sales Invoice name as the 1st column instead of `title` field.
    listView.columns[0].df = {
      'label': __('Name'),
      'fieldname': 'name'
    }

    // Set Sales Invoice Customer as 2nd column.
    const customerNameDf = listView.meta.fields.find(field => field.fieldname === 'customer_name')
    if (customerNameDf) {
      listView.columns.splice(2, 0, {
        type: 'Field',
        df: customerNameDf
      })
    }

    listView.get_header_html = new_get_header_html
    listView.render_header(true)
  },
}
