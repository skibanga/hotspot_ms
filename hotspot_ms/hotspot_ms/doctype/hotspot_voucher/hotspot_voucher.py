# Copyright (c) 2026, Sydney Kibanga and contributors
# For license information, please see license.txt

from frappe.model.document import Document
from frappe.utils import flt


class HotspotVoucher(Document):
	def before_save(self):
		if self.data_used_mb:
			self.data_used_gb = round(flt(self.data_used_mb) / 1024.0, 3)
		else:
			self.data_used_gb = 0.0
