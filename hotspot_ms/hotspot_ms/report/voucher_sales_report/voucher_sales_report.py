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

    # Always exclude Blocked vouchers
    conditions.append("v.status != 'Blocked'")

    where = " AND ".join(conditions)

    # ── Fetch voucher rows with plan price ──────────────────────────────────────
    rows = frappe.db.sql(
        f"""
        SELECT
            DATE(v.generated_on)   AS date,
            v.voucher_code,
            v.plan,
            IFNULL(p.price, 0)     AS price,
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
    # Every voucher generated = a sale. Revenue = sum of all plan prices.
    GATEWAY_RATE = 0.005  # 0.5% payment gateway charge
    total_vouchers = len(rows)
    total_revenue = sum(flt(r.price) for r in rows)
    gateway_charges = round(total_revenue * GATEWAY_RATE, 2)
    net_revenue = total_revenue - gateway_charges
    days_in_range = max(date_diff(to_date, from_date) + 1, 1)
    avg_per_day = net_revenue / days_in_range

    report_summary = [
        {
            "value": total_vouchers,
            "label": _("Total Vouchers Sold"),
            "datatype": "Int",
            "indicator": "blue",
        },
        {
            "value": total_revenue,
            "label": _("Gross Revenue (TSh)"),
            "datatype": "Currency",
            "indicator": "blue",
        },
        {
            "value": gateway_charges,
            "label": _("Gateway Charges 0.5% (TSh)"),
            "datatype": "Currency",
            "indicator": "orange",
        },
        {
            "value": net_revenue,
            "label": _("Net Revenue (TSh)"),
            "datatype": "Currency",
            "indicator": "green",
        },
        {
            "value": round(avg_per_day, 0),
            "label": _("Avg Net Revenue / Day"),
            "datatype": "Currency",
            "indicator": "green",
        },
    ]

    # ── Build line chart (vouchers generated per day) ───────────────────────────
    date_counts = {}
    date_revenue = {}
    current = from_date
    while current <= to_date:
        date_counts[str(current)] = 0
        date_revenue[str(current)] = 0
        current = add_days(current, 1)

    for r in rows:
        key = str(r.date)
        if key in date_counts:
            date_counts[key] += 1
            date_revenue[key] += flt(r.price)

    chart = {
        "data": {
            "labels": list(date_counts.keys()),
            "datasets": [
                {
                    "name": _("Revenue (TSh)"),
                    "values": list(date_revenue.values()),
                }
            ],
        },
        "type": "line",
        "lineOptions": {"regionFill": 1},
        "axisOptions": {"xIsSeries": True},
        "title": _("Daily Revenue Trend"),
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
            "width": 180,
        },
        {
            "fieldname": "plan",
            "label": _("Plan"),
            "fieldtype": "Link",
            "options": "Hotspot Plan",
            "width": 150,
        },
        {
            "fieldname": "price",
            "label": _("Price (TSh)"),
            "fieldtype": "Currency",
            "width": 130,
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
            "is_complimentary": r.is_complimentary,
        }
        for r in rows
    ]

    # ── Totals row at the bottom ─────────────────────────────────────────────────
    if data:
        data.append({
            "date": _("TOTAL"),
            "voucher_code": f"{total_vouchers} vouchers",
            "plan": "",
            "price": total_revenue,
            "is_complimentary": "",
            "bold": 1,
        })

    return columns, data, None, chart, report_summary
