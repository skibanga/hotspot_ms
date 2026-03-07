app_name = "hotspot_ms"
app_title = "Hotspot MS"
app_publisher = "Sydney Kibanga"
app_description = " "
app_email = "sydneykb38@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "hotspot_ms",
# 		"logo": "/assets/hotspot_ms/logo.png",
# 		"title": "Hotspot MS",
# 		"route": "/hotspot_ms",
# 		"has_permission": "hotspot_ms.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/hotspot_ms/css/hotspot_ms.css"
# app_include_js = "/assets/hotspot_ms/js/hotspot_ms.js"

# include js, css files in header of web template
# web_include_css = "/assets/hotspot_ms/css/hotspot_ms.css"
# web_include_js = "/assets/hotspot_ms/js/hotspot_ms.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "hotspot_ms/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "hotspot_ms/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "hotspot_ms.utils.jinja_methods",
# 	"filters": "hotspot_ms.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "hotspot_ms.install.before_install"
# after_install = "hotspot_ms.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "hotspot_ms.uninstall.before_uninstall"
# after_uninstall = "hotspot_ms.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "hotspot_ms.utils.before_app_install"
# after_app_install = "hotspot_ms.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "hotspot_ms.utils.before_app_uninstall"
# after_app_uninstall = "hotspot_ms.utils.after_app_uninstall"

# Run idempotent data seeding after each migrate
after_migrate = ["hotspot_ms.defaults.after_migrate"]

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "hotspot_ms.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"hotspot_ms.tasks.all"
# 	],
# 	"daily": [
# 		"hotspot_ms.tasks.daily"
# 	],
# 	"hourly": [
# 		"hotspot_ms.tasks.hourly"
# 	],
# 	"weekly": [
# 		"hotspot_ms.tasks.weekly"
# 	],
# 	"monthly": [
# 		"hotspot_ms.tasks.monthly"
# 	],
# }

# Keep hotspot sessions and vouchers in sync with expiry/data consumption.
scheduler_events = {
	"cron": {
		"*/1 * * * *": [
			"hotspot_ms.tasks.close_expired_or_used_sessions",
		]
	}
}

# Testing
# -------

# before_tests = "hotspot_ms.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "hotspot_ms.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "hotspot_ms.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["hotspot_ms.utils.before_request"]
# after_request = ["hotspot_ms.utils.after_request"]

# Job Events
# ----------
# before_job = ["hotspot_ms.utils.before_job"]
# after_job = ["hotspot_ms.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"hotspot_ms.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
