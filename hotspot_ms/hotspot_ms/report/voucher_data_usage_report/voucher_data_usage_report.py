import frappe
from frappe import _
from frappe.utils import getdate, date_diff, add_days, add_months, flt


def execute(filters=None):
    filters = filters or {}
    from_date = getdate(filters.get("from_date"))
    to_date = getdate(filters.get("to_date"))
    plan_filter = filters.get("plan")
    nas_device_filter = filters.get("nas_device")
    group_by = filters.get("group_by") or "Day"

    # ── Build WHERE clause ──────────────────────────────────────────────────────
    conditions = [
        "s.start_time >= %(from_date)s",
        "s.start_time < %(to_date_exclusive)s",
    ]
    query_params = {
        "from_date": from_date,
        "to_date_exclusive": add_days(to_date, 1),
    }

    if plan_filter:
        conditions.append("v.plan = %(plan)s")
        query_params["plan"] = plan_filter

    if nas_device_filter:
        conditions.append("s.nas_device = %(nas_device)s")
        query_params["nas_device"] = nas_device_filter

    where = " AND ".join(conditions)

    is_monthly = group_by == "Month"
    period_expr = (
        "DATE_FORMAT(s.start_time, '%%Y-%%m-01')"
        if is_monthly
        else "DATE(s.start_time)"
    )

    # ── Fetch session rows with plan (via voucher) ──────────────────────────────
    rows = frappe.db.sql(
        f"""
        SELECT
            {period_expr}            AS period,
            v.plan                  AS plan,
            s.nas_device             AS nas_device,
            COUNT(s.name)            AS total_sessions,
            SUM(IFNULL(s.total_mb, 0)) AS total_mb
        FROM `tabHotspot Session` s
        LEFT JOIN `tabHotspot Voucher` v ON v.name = s.voucher
        WHERE {where}
        GROUP BY {period_expr}, v.plan, s.nas_device
        ORDER BY period DESC, v.plan ASC, s.nas_device ASC
        """,
        query_params,
        as_dict=True,
    )

    # ── Compute KPI summary values ──────────────────────────────────────────────
    total_sessions = sum(r.total_sessions for r in rows)
    total_mb = sum(flt(r.total_mb) for r in rows)
    total_gb = total_mb / 1024
    days_in_range = max(date_diff(to_date, from_date) + 1, 1)
    avg_gb_per_day = total_gb / days_in_range

    report_summary = [
        {
            "value": total_sessions,
            "label": _("Total Sessions"),
            "datatype": "Int",
            "indicator": "blue",
        },
        {
            "value": round(total_gb, 2),
            "label": _("Total Data Used (GB)"),
            "datatype": "Float",
            "indicator": "orange",
        },
        {
            "value": round(avg_gb_per_day, 2),
            "label": _("Avg Data / Day (GB)"),
            "datatype": "Float",
            "indicator": "orange",
        },
    ]

    # ── Build period buckets (Day or Month) for the table & chart ───────────────
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

    period_gb = {p: 0 for p in periods}

    for r in rows:
        key = getdate(r.period)
        if is_monthly:
            key = month_start(key)
        if key in period_gb:
            period_gb[key] += flt(r.total_mb) / 1024

    chart_labels = [
        p.strftime("%b %Y") if is_monthly else str(p) for p in periods
    ]
    chart_values = [round(period_gb[p], 2) for p in periods]

    chart = {
        "data": {
            "labels": chart_labels,
            "datasets": [
                {
                    "name": _("Data Used (GB)"),
                    "values": chart_values,
                }
            ],
        },
        "type": "line",
        "lineOptions": {"regionFill": 1},
        "axisOptions": {"xIsSeries": not is_monthly},
        "title": _("Monthly Data Usage Trend") if is_monthly else _("Daily Data Usage Trend"),
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
            "fieldname": "total_sessions",
            "label": _("Total Sessions"),
            "fieldtype": "Int",
            "width": 130,
        },
        {
            "fieldname": "total_data_gb",
            "label": _("Total Data Used (GB)"),
            "fieldtype": "Float",
            "precision": 2,
            "width": 170,
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
                "total_sessions": r.total_sessions,
                "total_data_gb": round(flt(r.total_mb) / 1024, 2),
            }
        )

    # ── Totals row at the bottom ─────────────────────────────────────────────────
    if data:
        data.append({
            "period": _("TOTAL"),
            "plan": "",
            "nas_device": "",
            "total_sessions": total_sessions,
            "total_data_gb": round(total_gb, 2),
            "bold": 1,
        })

    return columns, data, None, chart, report_summary
