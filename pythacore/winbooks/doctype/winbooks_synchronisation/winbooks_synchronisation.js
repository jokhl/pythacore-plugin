// Copyright (c) 2021, Kano Solutions SRL

// Reference files:
//
// 		/frappe/public/js/frappe/socketio_client.js

frappe.ui.form.on('Winbooks Synchronisation', {
	setup(frm) {
		frappe.realtime.on('winbooks_sync_refresh', ({ sync_doc_name }) => {
			if (sync_doc_name !== frm.doc.name) return;
			frappe.model.clear_doc('Winbooks Synchronisation', frm.doc.name);
			frappe.model.with_doc('Winbooks Synchronisation', frm.doc.name).then(() => {
				frm.refresh();
			});
		});
		frappe.realtime.on('winbooks_sync_progress', data => {
			// This handles the case where a progress update arrives *after* finishing a sync.
			// This typically happens when there is nothing to sync.
			if (frm.doc.status === 'Success' || frm.doc.status === 'Error' || frm.doc.status === 'Partial') return

			if (data.sync_doc_name !== frm.doc.name) {
				return;
			}

			if (data.total > 0) {
				let percent = Math.floor((data.current * 100) / data.total);
				frm.dashboard.show_progress(__('Sync Progress'), percent, data.message);
			} else {
				frm.dashboard.show_progress(__('Sync Progress'), 0, data.message);
			}

			frm.page.set_indicator(__('In Progress'), 'orange');

			// hide progress when complete
			if (data.current === data.total) {
				setTimeout(() => {
					frm.dashboard.hide();
					frm.refresh();
				}, 2000);
			}
		});
	},

	refresh(frm) {
		frm.page.hide_icon_group();
		frm.trigger('update_primary_action');
		frm.trigger('update_indicators');
		frm.trigger('show_sync_details');
		frm.trigger('show_sync_status');
		frm.trigger('show_error');
	},

	onload_post_render(frm) {
		frm.trigger('update_primary_action');
	},

	after_save(frm) {
		frm.events.start_sync(frm);
	},

	update_primary_action(frm) {
		frm.disable_save();

		if (frm.is_dirty()) {
			frm.page.set_primary_action(__('Start Synchronisation'), () => {
				frm.save();
			});
			return;
		}

		if (frm.doc.status !== 'Success') {
			if (frm.is_new() === true) {
				frm.page.set_primary_action(__('Save'), () => frm.save());
			} else {
				if (frm.doc.status === 'Pending') {
					frm.page.set_primary_action(__('Start Synchronisation'), () => frm.events.start_sync(frm));
				} else {
					frm.page.set_primary_action(__('Retry'), () => {
						frm.trigger('hide_sync_details')
						frm.trigger('hide_error')
						frappe.new_doc('Winbooks Synchronisation')
					});
				}
			}
		}
	},

	update_indicators(frm) {
		const indicator = frappe.get_indicator(frm.doc);

		if (indicator) {
			frm.page.set_indicator(indicator[0], indicator[1]);
		} else {
			frm.page.clear_indicator();
		}
	},

	show_sync_status(frm) {
		frm.dashboard.set_headline(frm.doc.headline);
	},

	show_error(frm) {
		if (frm.doc.error_message || frm.doc.warning_message) {
			frm.toggle_display('errors_section', true);

			if (frm.doc.error_message) {
				frm.get_field('error_preview').$wrapper.html(`
					<p class="alert alert-danger">${frm.doc.error_message}</p>
				`);
			}

			if (frm.doc.warning_message) {
				frm.get_field('warning_preview').$wrapper.html(`
					<p class="alert alert-warning">${frm.doc.warning_message}</p>
				`);
			}
		} else {
			frm.toggle_display('errors_section', false);
		}
	},

	hide_error(frm) {
		frm.toggle_display('errors_section', false);
	},

	start_sync(frm) {
		frm
			.call({
				method: 'form_start_sync',
				args: { sync_doc_name: frm.doc.name },
				btn: frm.page.btn_primary
			})
			.then(r => {
				if (r.message === true) {
					frm.trigger('hide_error');
					frm.trigger('hide_sync_details');
					frm.disable_save();
				}
			});
	},

	hide_sync_details(frm) {
		frm.toggle_display('sync_details_section', false);
	},

	show_sync_details(frm) {
		let sync_log = JSON.parse(frm.doc.sync_log || '[]');
		let logs = sync_log;
		frm.toggle_display('sync_details_section', (frm.doc.status !== 'Pending' && logs.length > 0));

		if (logs.length === 0) {
			frm.get_field('sync_log_preview').$wrapper.empty();
			return;
		}

		let rows = logs
			.map(log => {
				let messageHtml = log.message ?? ''
				let documentHtml = `${log.doctype}
					<span class="underline">
						${frappe.utils.get_form_link(
					log.doctype,
					log.name,
					true
				)}
					<span>`;

				let indicator_color = 'gray';
				if (log.status === 'Success') indicator_color = 'green text-success';
				else if (log.status === 'Warning') indicator_color = 'yellow text-warning';
				else if (log.status === 'Error') indicator_color = 'red text-danger';

				let title = __('Pending');
				if (log.status === 'Success') title = __('Success');
				else if (log.status === 'Warning') title = __('Warning');
				else if (log.status === 'Error') title = __('Error');

				return `<tr>
					<td>${documentHtml}</td>
					<td>
						<div class="indicator ${indicator_color}">${title}</div>
					</td>
					<td>
						${messageHtml}
					</td>
				</tr>`;
			})
			.join('');

		frm.get_field('sync_log_preview').$wrapper.html(`
			<table class="table table-bordered">
				<tr class="text-muted">
					<th width="20%">${__('Document')}</th>
					<th width="10%">${__('Status')}</th>
					<th width="70%">${__('Message')}</th>
				</tr>
				${rows}
			</table>
		`);
	},
});
