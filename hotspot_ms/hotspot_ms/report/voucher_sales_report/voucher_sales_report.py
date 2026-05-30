import frappe
from frappe import _
from frappe.utils import getdate, date_diff, add_days, flt


def execute(filters=None):
    filters = filters or {}
    from_date = getdate(filters.get("from_date"))
    to_date = getdate(filters.get("to_date"))
    plan_filter = filters.get("plan")
    include_complimentary = filters.get("include_complimentary")

    # ── Build WHERE clause ──────────────────────────────────────────────────────
    conditions = [
        "v.generated_on >= %(from_date)s",
        "v.generated_on < %(to_date_exclusive)s",
    ]
    query_params = {
        "from_date": from_date,
        "to_date_exclusive": add_days(to_date, 1),
    }

    if plan_filter:
        conditions.append("v.plan = %(plan)s")
        query_params["plan"] = plan_filter

    if not include_complimentary:
        conditions.append("IFNULL(v.is_complimentary, 0) = 0")

    where = " AND ".join(conditions)

    # ── Fetch voucher rows with plan price ──────────────────────────────────────
    rows = frappe.db.sql(
        f"""
        SELECT
            DATE(v.generated_on)   AS date,
            v.name,
            v.voucher_code,
            v.plan,
            IFNULL(p.price, 0)     AS price,
            v.status,
            v.activated_on,
            v.is_complimentary
        FROM `tabHotspot Voucher` v
        LEFT JOIN `tabHotspot Plan` p ON p.name = v.plan
        WHERE {where}
        ORDER BY v.generated_on DESC
        """,
        query_params,
        as_dict=True,
    )

    # ── Compute KPI summary values ──────────────────────────────────────────────
    total_vouchers = len(rows)
    activated = [r for r in rows if r.status in ("Active", "Used")]
    total_revenue = sum(flt(r.price) for r in activated)
    days_in_range = max(date_diff(to_date, from_date) + 1, 1)
    avg_per_day = total_revenue / days_in_range

    report_summary = [
        {
            "value": total_vouchers,
            "label": _("Total Vouchers"),
            "datatype": "Int",
            "indicator": "blue",
        },
        {
            "value": len(activated),
            "label": _("Activated"),
            "datatype": "Int",
            "indicator": "green",
        },
        {
            "value": total_revenue,
            "label": _("Total Revenue (TSh)"),
            "datatype": "Currency",
            "indicator": "green",
        },
        {
            "value": round(avg_per_day, 0),
            "label": _("Avg Revenue / Day"),
            "datatype": "Currency",
            "indicator": "blue",
        },
    ]

    # ── Build line chart (vouchers generated per day) ───────────────────────────
    # Create a dict of date → count
    date_counts = {}
    current = from_date
    while current <= to_date:
        date_counts[str(current)] = 0
        current = add_days(current, 1)

    for r in rows:
        key = str(r.date)
        if key in date_counts:
            date_counts[key] += 1

    chart = {
        "data": {
            "labels": list(date_counts.keys()),
            "datasets": [
                {
                    "name": _("Vouchers Generated"),
                    "values": list(date_counts.values()),
                    "chartType": "line",
                }
            ],
        },
        "type": "line",
        "lineOptions": {"regionFill": 1},
        "axisOptions": {"xIsSeries": True},
        "title": _("Daily Voucher Generation Trend"),
    }

    # ── Columns ──────────────────────────────────────────────────────────────────
    columns = [
        {
            "fieldname": "date",
            "label": _("Date"),
            "fieldtype": "Date",
            "width": 110,
        },
        {
            "fieldname": "voucher_code",
            "label": _("Voucher Code"),
            "fieldtype": "Link",
            "options": "Hotspot Voucher",
            "width": 160,
        },
        {
            "fieldname": "plan",
            "label": _("Plan"),
            "fieldtype": "Link",
            "options": "Hotspot Plan",
            "width": 140,
        },
        {
            "fieldname": "price",
            "label": _("Price (TSh)"),
            "fieldtype": "Currency",
            "width": 120,
        },
        {
            "fieldname": "status",
            "label": _("Status"),
            "fieldtype": "Data",
            "width": 100,
        },
        {
            "fieldname": "activated_on",
            "label": _("Activated On"),
            "fieldtype": "Datetime",
            "width": 160,
        },
        {
            "fieldname": "is_complimentary",
            "label": _("Complimentary"),
            "fieldtype": "Check",
            "width": 120,
        },
    ]

    # ── Format rows for display ──────────────────────────────────────────────────
    data = [
        {
            "date": r.date,
            "voucher_code": r.voucher_code,
            "plan": r.plan,
            "price": r.price,
            "status": r.status,
            "activated_on": r.activated_on,
            "is_complimentary": r.is_complimentary,
        }
        for r in rows
    ]

    return columns, data, None, chart, report_summary
