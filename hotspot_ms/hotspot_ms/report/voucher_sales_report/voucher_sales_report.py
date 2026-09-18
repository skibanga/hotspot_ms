import frappe
from frappe import _
from frappe.utils import getdate, date_diff, add_days, add_months, flt


def execute(filters=None):
    filters = filters or {}
    from_date = getdate(filters.get("from_date"))
    to_date = getdate(filters.get("to_date"))
    plan_filter = filters.get("plan")
    nas_device_filter = filters.get("nas_device")
    include_complimentary = filters.get("include_complimentary")
    group_by = filters.get("group_by") or "Day"

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

    if nas_device_filter:
        conditions.append("v.last_nas = %(nas_device)s")
        query_params["nas_device"] = nas_device_filter

    if not include_complimentary:
        conditions.append("IFNULL(v.is_complimentary, 0) = 0")

    # Always exclude Blocked vouchers
    conditions.append("v.status != 'Blocked'")

    where = " AND ".join(conditions)

    period_expr = (
        "DATE_FORMAT(v.generated_on, '%%Y-%%m-01')"
        if group_by == "Month"
        else "DATE(v.generated_on)"
    )

    # ── Fetch voucher rows with plan price ──────────────────────────────────────
    rows = frappe.db.sql(
        f"""
        SELECT
            {period_expr}            AS period,
            v.plan,
            v.last_nas              AS nas_device,
            COUNT(v.name)           AS total_vouchers,
            SUM(IFNULL(p.price, 0)) AS total_revenue
        FROM `tabHotspot Voucher` v
        LEFT JOIN `tabHotspot Plan` p ON p.name = v.plan
        WHERE {where}
        GROUP BY {period_expr}, v.plan, v.last_nas
        ORDER BY period DESC, v.plan ASC, v.last_nas ASC
        """,
        query_params,
        as_dict=True,
    )

    # ── Compute KPI summary values ──────────────────────────────────────────────
    # Every voucher generated = a sale. Revenue = sum of all plan prices.
    total_vouchers = sum(r.total_vouchers for r in rows)
    total_revenue = sum(flt(r.total_revenue) for r in rows)
    days_in_range = max(date_diff(to_date, from_date) + 1, 1)
    avg_per_day = total_revenue / days_in_range

    report_summary = [
        {
            "value": total_vouchers,
            "label": _("Total Vouchers Sold"),
            "datatype": "Int",
            "indicator": "blue",
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
            "indicator": "green",
        },
    ]

    # ── Build period buckets (Day or Month) for the table & chart ───────────────
    is_monthly = group_by == "Month"

    def month_start(d):
        return d.replace(day=1)

    periods = []
    if is_monthly:
        current = month_start(from_date)
        end = month_start(to_date)
        while current <= end:
            periods.append(current)
            current = add_months(current, 1)
    else:
        current = from_date
        while current <= to_date:
            periods.append(current)
            current = add_days(current, 1)

    period_counts = {p: 0 for p in periods}
    period_revenue = {p: 0 for p in periods}

    for r in rows:
        key = getdate(r.period)
        if is_monthly:
            key = month_start(key)
        if key in period_counts:
            period_counts[key] += r.total_vouchers
            period_revenue[key] += flt(r.total_revenue)

    chart_labels = [
        p.strftime("%b %Y") if is_monthly else str(p) for p in periods
    ]
    chart_values = [period_revenue[p] for p in periods]

    chart = {
        "data": {
            "labels": chart_labels,
            "datasets": [
                {
                    "name": _("Revenue (TSh)"),
                    "values": chart_values,
                }
            ],
        },
        "type": "line" if is_monthly else "line",
        "lineOptions": {"regionFill": 1},
        "axisOptions": {"xIsSeries": not is_monthly},
        "title": _("Monthly Revenue Trend") if is_monthly else _("Daily Revenue Trend"),
    }

    # ── Columns ──────────────────────────────────────────────────────────────────
    period_column = (
        {
            "fieldname": "period",
            "label": _("Month"),
            "fieldtype": "Data",
            "width": 130,
        }
        if is_monthly
        else {
            "fieldname": "period",
            "label": _("Date"),
            "fieldtype": "Date",
            "width": 130,
        }
    )

    columns = [
        period_column,
        {
            "fieldname": "plan",
            "label": _("Plan"),
            "fieldtype": "Link",
            "options": "Hotspot Plan",
            "width": 180,
        },
        {
            "fieldname": "nas_device",
            "label": _("NAS Device"),
            "fieldtype": "Link",
            "options": "Nas Device",
            "width": 160,
        },
        {
            "fieldname": "total_vouchers",
            "label": _("Total Vouchers"),
            "fieldtype": "Int",
            "width": 150,
        },
        {
            "fieldname": "total_revenue",
            "label": _("Total Revenue (TSh)"),
            "fieldtype": "Currency",
            "width": 180,
        },
    ]

    # ── Format rows for display ──────────────────────────────────────────────────
    data = []
    for r in rows:
        key = getdate(r.period)
        period_value = key.strftime("%b %Y") if is_monthly else key
        data.append(
            {
                "period": period_value,
                "plan": r.plan,
                "nas_device": r.nas_device,
                "total_vouchers": r.total_vouchers,
                "total_revenue": r.total_revenue,
            }
        )

    # ── Totals row at the bottom ─────────────────────────────────────────────────
    if data:
        data.append({
            "period": _("TOTAL"),
            "plan": "",
            "nas_device": "",
            "total_vouchers": total_vouchers,
            "total_revenue": total_revenue,
            "bold": 1,
        })

    return columns, data, None, chart, report_summary
