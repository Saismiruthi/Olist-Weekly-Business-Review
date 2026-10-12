
"""Generate data-driven charts and a concise PDF business review."""

import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image,
    PageBreak,
    Table,
    TableStyle,
    KeepTogether,
)

# --------------------------------------------------
# Configuration
# --------------------------------------------------

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing. Check your .env file.")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

OUT = Path("reports")
OUT.mkdir(exist_ok=True)


def read_query(conn, sql):
    """Execute SQL and return a DataFrame."""
    return pd.read_sql(text(sql), conn)


def money(value):
    return f"R$ {float(value):,.2f}"


def pct(value):
    return f"{float(value):.2f}%"


def create_chart(path, title, xlabel, ylabel):
    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.tight_layout()
    plt.savefig(path, dpi=160, bbox_inches="tight")
    plt.close()


try:
    with engine.connect() as conn:

        # --------------------------------------------------
        # 1. Monthly payment revenue and month-over-month growth
        # --------------------------------------------------

        monthly = read_query(conn, """
            WITH monthly_totals AS (
                SELECT
                    DATE_TRUNC('month', purchase_ts)::date AS month_start,
                    SUM(payment_total) AS revenue
                FROM mart_order_summary
                WHERE purchase_ts IS NOT NULL
                GROUP BY 1
            ),
            monthly_growth AS (
                SELECT
                    month_start,
                    revenue,
                    LAG(revenue) OVER (
                        ORDER BY month_start
                    ) AS previous_revenue
                FROM monthly_totals
            )
            SELECT
                month_start,
                revenue,
                previous_revenue,
                ROUND(
                    100.0 * (revenue - previous_revenue)
                    / NULLIF(previous_revenue, 0),
                    2
                ) AS revenue_growth_pct
            FROM monthly_growth
            ORDER BY month_start
        """)

        # --------------------------------------------------
        # 2. Delivery performance and review score
        # --------------------------------------------------

        delivery = read_query(conn, """
            WITH delivery_groups AS (
                SELECT
                    CASE
                        WHEN delivery_delay_days < 0 THEN 'Early'
                        WHEN delivery_delay_days = 0 THEN 'On time'
                        ELSE 'Late'
                    END AS bucket,
                    review_score
                FROM mart_order_summary
                WHERE order_status = 'delivered'
                  AND delivery_delay_days IS NOT NULL
                  AND review_score IS NOT NULL
            )
            SELECT
                bucket,
                COUNT(*) AS orders,
                ROUND(AVG(review_score)::numeric, 2) AS avg_review
            FROM delivery_groups
            GROUP BY bucket
            ORDER BY CASE bucket
                WHEN 'Early' THEN 1
                WHEN 'On time' THEN 2
                ELSE 3
            END
        """)

        # --------------------------------------------------
        # 3. Top customer states by order count
        # --------------------------------------------------

        states = read_query(conn, """
            SELECT
                customer_state AS state,
                COUNT(*) AS orders
            FROM mart_order_summary
            GROUP BY customer_state
            ORDER BY orders DESC
            LIMIT 10
        """)

        # --------------------------------------------------
        # 4. Review score distribution
        # --------------------------------------------------

        reviews = read_query(conn, """
            SELECT
                review_score,
                COUNT(*) AS review_count
            FROM stg_reviews
            WHERE review_score BETWEEN 1 AND 5
            GROUP BY review_score
            ORDER BY review_score
        """)

        # --------------------------------------------------
        # 5. Data quality checks and source-data exceptions
        # --------------------------------------------------

        quality = read_query(conn, """
            SELECT 'Null order IDs' AS check_name, COUNT(*) AS failures
            FROM raw_orders
            WHERE order_id IS NULL OR BTRIM(order_id) = ''

            UNION ALL

            SELECT 'Duplicate order IDs', COUNT(*)
            FROM (
                SELECT order_id
                FROM raw_orders
                GROUP BY order_id
                HAVING COUNT(*) > 1
            ) d

            UNION ALL

            SELECT 'Delivery before purchase', COUNT(*)
            FROM stg_orders
            WHERE delivered_ts IS NOT NULL
              AND purchase_ts IS NOT NULL
              AND delivered_ts < purchase_ts

            UNION ALL

            SELECT 'Orders without customer', COUNT(*)
            FROM stg_orders o
            LEFT JOIN stg_customers c
                ON o.customer_id = c.customer_id
            WHERE c.customer_id IS NULL

            UNION ALL

            SELECT 'Invalid review scores', COUNT(*)
            FROM stg_reviews
            WHERE review_score IS NOT NULL
              AND review_score NOT BETWEEN 1 AND 5

            UNION ALL

            SELECT 'Payment mismatches with item records', COUNT(*)
            FROM mart_order_summary m
            WHERE m.payment_total > 0
              AND ABS(
                    m.payment_total - m.item_plus_freight
                  ) > 0.05
              AND EXISTS (
                  SELECT 1
                  FROM raw_order_items i
                  WHERE i.order_id = m.order_id
              )

            UNION ALL

            SELECT 'Paid orders without item records', COUNT(*)
            FROM mart_order_summary m
            WHERE m.payment_total > 0
              AND NOT EXISTS (
                  SELECT 1
                  FROM raw_order_items i
                  WHERE i.order_id = m.order_id
              )

            UNION ALL

            SELECT 'Delivered orders missing delivery timestamp',
                   COUNT(*)
            FROM stg_orders
            WHERE order_status = 'delivered'
              AND delivered_ts IS NULL
        """)

        # --------------------------------------------------
        # 6. North Star and supporting metrics
        # --------------------------------------------------

        metrics = read_query(conn, """
            SELECT
                COUNT(*) FILTER (
                    WHERE order_status = 'delivered'
                      AND delivered_ts IS NOT NULL
                      AND estimated_delivery_ts IS NOT NULL
                ) AS delivery_eligible,

                COUNT(*) FILTER (
                    WHERE order_status = 'delivered'
                      AND delivered_ts IS NOT NULL
                      AND estimated_delivery_ts IS NOT NULL
                      AND delivered_ts::date
                          <= estimated_delivery_ts::date
                ) AS on_time_delivered,

                COUNT(*) FILTER (
                    WHERE order_status = 'delivered'
                      AND delivered_ts IS NOT NULL
                      AND estimated_delivery_ts IS NOT NULL
                      AND delivered_ts::date
                          > estimated_delivery_ts::date
                ) AS late_delivered,

                ROUND(AVG(review_score)::numeric, 2) AS avg_review,

                COUNT(*) AS all_orders
            FROM mart_order_summary
        """)

        # Repeat-purchase rate uses customer_unique_id.
        repeat = read_query(conn, """
            WITH eligible AS (
                SELECT
                    customer_unique_id,
                    COUNT(*) AS order_count
                FROM mart_order_summary
                WHERE customer_unique_id IS NOT NULL
                  AND order_status <> 'canceled'
                GROUP BY customer_unique_id
            )
            SELECT
                COUNT(*) AS eligible_customers,
                COUNT(*) FILTER (
                    WHERE order_count >= 2
                ) AS repeat_customers,
                ROUND(
                    100.0 * COUNT(*) FILTER (
                        WHERE order_count >= 2
                    ) / NULLIF(COUNT(*), 0),
                    2
                ) AS repeat_purchase_rate
            FROM eligible
        """)

        # Top 3 product categories per customer state.
        category_sql_path = Path(
            "sql/analytics/02_top3_categories_by_state.sql"
        )
        if category_sql_path.exists():
            category_sql = category_sql_path.read_text(
                encoding="utf-8"
            )
            categories = read_query(conn, category_sql)
        else:
            categories = pd.DataFrame()

    # --------------------------------------------------
    # Calculate actual findings from query results
    # --------------------------------------------------

    m = metrics.iloc[0]
    r = repeat.iloc[0]

    eligible_delivery = int(m["delivery_eligible"] or 0)
    on_time_count = int(m["on_time_delivered"] or 0)
    late_count = int(m["late_delivered"] or 0)

    on_time_rate = (
        100 * on_time_count / eligible_delivery
        if eligible_delivery else 0
    )
    late_rate = (
        100 * late_count / eligible_delivery
        if eligible_delivery else 0
    )

    avg_review = (
        float(m["avg_review"])
        if pd.notna(m["avg_review"]) else 0
    )
    repeat_rate = (
        float(r["repeat_purchase_rate"])
        if pd.notna(r["repeat_purchase_rate"]) else 0
    )

    latest_month = monthly.iloc[-1] if not monthly.empty else None
    previous_month = (
        monthly.iloc[-2] if len(monthly) >= 2 else None
    )

    # --------------------------------------------------
    # Chart 1: Monthly revenue
    # --------------------------------------------------

    if not monthly.empty:
        plt.figure(figsize=(8, 3.5))
        plt.plot(
            monthly["month_start"],
            monthly["revenue"],
            marker="o",
        )
        plt.xticks(rotation=45)
        create_chart(
            OUT / "monthly_revenue.png",
            "Monthly payment revenue",
            "Purchase month",
            "Revenue (BRL)",
        )

    # --------------------------------------------------
    # Chart 2: Delivery performance and reviews
    # --------------------------------------------------

    if not delivery.empty:
        plt.figure(figsize=(6, 3.5))
        plt.bar(delivery["bucket"], delivery["avg_review"])
        create_chart(
            OUT / "delivery_reviews.png",
            "Average review score by delivery performance",
            "Delivery performance",
            "Average review (1–5)",
        )

    # --------------------------------------------------
    # Chart 3: Order volume by state
    # --------------------------------------------------

    if not states.empty:
        plt.figure(figsize=(7, 3.5))
        plt.bar(states["state"], states["orders"])
        create_chart(
            OUT / "orders_by_state.png",
            "Top 10 customer states by order count",
            "Customer state",
            "Orders",
        )

    # --------------------------------------------------
    # Chart 4: Review distribution
    # --------------------------------------------------

    if not reviews.empty:
        plt.figure(figsize=(6, 3.5))
        plt.bar(
            reviews["review_score"].astype(str),
            reviews["review_count"],
        )
        create_chart(
            OUT / "review_distribution.png",
            "Review score distribution",
            "Review score",
            "Number of reviews",
        )

    # --------------------------------------------------
    # Build a deliberately five-page PDF report
    # --------------------------------------------------

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="SmallText",
        parent=styles["BodyText"],
        fontSize=8,
        leading=10,
        alignment=TA_LEFT,
    ))
    styles.add(ParagraphStyle(
        name="MemoText",
        parent=styles["BodyText"],
        fontSize=9,
        leading=13,
        spaceAfter=5,
    ))

    story = []

    # PAGE 1 — Executive summary and metric definitions
    story.extend([
        Paragraph(
            "Weekly Business Review — Olist E-commerce",
            styles["Title"],
        ),
        Paragraph(
            "Source: Brazilian E-Commerce Public Dataset by Olist. "
            "The data covers a historical period, not current marketplace performance.",
            styles["SmallText"],
        ),
        Spacer(1, 5 * mm),
        Paragraph("1. Executive summary", styles["Heading1"]),
        Paragraph(
            f"<b>North Star — on-time delivery rate:</b> {pct(on_time_rate)} "
            f"({on_time_count:,} on-time orders out of {eligible_delivery:,} "
            "delivered orders with both delivery and estimated dates).",
            styles["BodyText"],
        ),
        Spacer(1, 2 * mm),
        Paragraph(
            f"<b>Supporting indicators:</b> average review score "
            f"{avg_review:.2f}/5; repeat-purchase rate {pct(repeat_rate)}; "
            f"late delivery rate {pct(late_rate)}.",
            styles["BodyText"],
        ),
        Spacer(1, 4 * mm),
        Paragraph("2. Metric definitions", styles["Heading1"]),
        Paragraph(
            "<b>On-time delivery rate:</b> delivered orders received on or "
            "before the estimated date divided by delivered orders with both "
            "dates, multiplied by 100.",
            styles["SmallText"],
        ),
        Paragraph(
            "<b>Late delivery rate:</b> delivered orders received after the "
            "estimated date divided by the same eligible delivered-order "
            "population, multiplied by 100.",
            styles["SmallText"],
        ),
        Paragraph(
            "<b>Average review:</b> mean recorded review score on the 1–5 scale. "
            "<b>Repeat-purchase rate:</b> distinct customers with at least two "
            "non-canceled orders divided by distinct customers with at least "
            "one non-canceled order, multiplied by 100. <b>Revenue:</b> sum "
            "of payment values grouped by purchase month.",
            styles["SmallText"],
        ),
        Spacer(1, 3 * mm),
        Paragraph("How to read this report", styles["Heading2"]),
        Paragraph(
            "The North Star tracks delivery reliability. Review score and "
            "repeat purchase provide customer-experience context; revenue "
            "tracks payment value, which is not necessarily the same as "
            "recognized accounting revenue. Findings are descriptive and "
            "should be validated before operational decisions.",
            styles["SmallText"],
        ),
        PageBreak(),
    ])

    # PAGE 2 — Data quality and handling
    story.extend([
        Paragraph("3. Data quality and exception handling", styles["Heading1"]),
        Paragraph(
            "The checks below count source-data exceptions. A non-zero count "
            "does not, by itself, identify the cause. Preserve the source "
            "records and investigate exceptions rather than silently "
            "deleting rows or inventing replacement values.",
            styles["SmallText"],
        ),
        Spacer(1, 3 * mm),
    ])

    qdata = [["Check", "Exception rows"]]
    for row in quality.itertuples(index=False):
        qdata.append([str(row.check_name), f"{int(row.failures):,}"])

    quality_table = Table(
        qdata,
        colWidths=[112 * mm, 35 * mm],
        repeatRows=1,
    )
    quality_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#174A70")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("PADDING", (0, 0), (-1, -1), 5),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.extend([
        quality_table,
        Spacer(1, 4 * mm),
        Paragraph("Interpretation and handling", styles["Heading2"]),
        Paragraph(
            "Payment mismatches and paid orders without item records should "
            "be investigated with order-level reconciliation. Delivered orders "
            "missing delivery timestamps should be excluded from the on-time "
            "rate denominator and reported separately. The pipeline's "
            "blocking rules are defined in its quality-check code; warnings "
            "should remain visible in the run logs.",
            styles["SmallText"],
        ),
        Spacer(1, 3 * mm),
        Paragraph(
            "<b>Control recommendation:</b> review the exception counts after "
            "each ingestion run and compare them with the prior run. Treat "
            "unexpected increases as a data incident before using the affected "
            "metrics for decisions.",
            styles["SmallText"],
        ),
        PageBreak(),
    ])

    # PAGE 3 — Revenue and delivery charts
    story.extend([
        Paragraph("4. Business charts — revenue and delivery", styles["Heading1"]),
        Paragraph(
            "Figure 1 shows monthly payment revenue. Figure 2 compares average "
            "review scores across delivery-performance groups. The measures "
            "describe the historical dataset and do not prove causation.",
            styles["SmallText"],
        ),
        Spacer(1, 3 * mm),
    ])

    for filename, caption in [
        ("monthly_revenue.png", "Figure 1. Monthly payment revenue (BRL)"),
        ("delivery_reviews.png", "Figure 2. Average review score by delivery performance"),
    ]:
        chart_path = OUT / filename
        if chart_path.exists():
            story.extend([
                Image(str(chart_path), width=145 * mm, height=57 * mm),
                Paragraph(caption, styles["SmallText"]),
                Spacer(1, 3 * mm),
            ])
        else:
            story.append(Paragraph(
                f"Chart not found: {filename}", styles["SmallText"]
            ))

    if latest_month is not None:
        story.append(Paragraph(
            f"<b>Revenue note:</b> the latest month in the dataset is "
            f"{pd.to_datetime(latest_month['month_start']).strftime('%B %Y')}, "
            f"with payment revenue of {money(latest_month['revenue'])}.",
            styles["SmallText"],
        ))
    story.append(PageBreak())

    # PAGE 4 — Geographic, review and SQL analysis
    story.extend([
        Paragraph("5. Customer and review analysis", styles["Heading1"]),
        Paragraph(
            "The state chart highlights where orders are concentrated; the "
            "review distribution shows the frequency of recorded scores. "
            "These views can guide further investigation but do not explain "
            "why a customer bought or rated an order.",
            styles["SmallText"],
        ),
        Spacer(1, 3 * mm),
    ])

    for filename, caption in [
        ("orders_by_state.png", "Figure 3. Top 10 customer states by order count"),
        ("review_distribution.png", "Figure 4. Review score distribution"),
    ]:
        chart_path = OUT / filename
        if chart_path.exists():
            story.extend([
                Image(str(chart_path), width=145 * mm, height=57 * mm),
                Paragraph(caption, styles["SmallText"]),
                Spacer(1, 3 * mm),
            ])
        else:
            story.append(Paragraph(
                f"Chart not found: {filename}", styles["SmallText"]
            ))

    story.extend([
        Paragraph("SQL analyses included in the project", styles["Heading2"]),
        Paragraph(
            "1. Month-over-month payment revenue and growth using LAG(). "
            "2. Top three product categories by customer state using ranking. "
            "3. Seven-day rolling daily order count using a window frame. "
            "4. Repeat-purchase rate based on customer_unique_id. "
            "5. Delivery delay compared with review score.",
            styles["SmallText"],
        ),
        Paragraph(
            "For category-level revenue, use item prices; for the monthly "
            "payment-revenue chart in this report, use payment values. Do not "
            "treat these two measures as interchangeable.",
            styles["SmallText"],
        ),
        PageBreak(),
    ])

    # PAGE 5 — One-page VP memo
    story.extend([
        Paragraph("6. VP memo", styles["Heading1"]),
        Paragraph(
            "<b>To:</b> VP, E-commerce<br/>"
            "<b>Subject:</b> Improve delivery reliability to protect customer experience",
            styles["MemoText"],
        ),
        Spacer(1, 3 * mm),
        Paragraph("<b>Decision requested</b>", styles["Heading2"]),
        Paragraph(
            "Pilot a delivery-exception workflow for orders at risk of missing "
            "their estimated delivery date. Keep on-time delivery rate as the "
            "North Star and monitor customer feedback and repeat purchasing "
            "as supporting indicators.",
            styles["MemoText"],
        ),
        Paragraph("<b>Evidence</b>", styles["Heading2"]),
        Paragraph(
            f"The historical dataset's on-time delivery rate is {pct(on_time_rate)}, "
            f"while {pct(late_rate)} of eligible delivered orders arrived after "
            f"their estimate. The average recorded review score is {avg_review:.2f}/5, "
            f"and repeat-purchase rate is {pct(repeat_rate)} under the report's "
            "non-canceled-order definition. These observations do not establish "
            "that delivery timing caused a particular review score.",
            styles["MemoText"],
        ),
    ])

    if latest_month is not None and previous_month is not None:
        growth = latest_month["revenue_growth_pct"]
        if pd.notna(growth):
            story.append(Paragraph(
                f"The latest month in the dataset is "
                f"{pd.to_datetime(latest_month['month_start']).strftime('%B %Y')}, "
                f"with payment revenue of {money(latest_month['revenue'])}; "
                f"the reported month-over-month change is {float(growth):.2f}%. "
                "Because this is the end of a historical dataset, it should not "
                "be interpreted as current business performance.",
                styles["MemoText"],
            ))

    story.extend([
        Paragraph("<b>Recommended actions</b>", styles["Heading2"]),
        Paragraph(
            "1. Flag orders approaching their estimated date and route them to "
            "an operations exception queue.<br/>"
            "2. Notify affected customers proactively when delays are likely.<br/>"
            "3. Review on-time rate, late rate, and review score together after "
            "the pilot; compare with a baseline before expanding.<br/>"
            "4. Investigate payment/item mismatches and missing timestamps before "
            "using affected records for financial or service-level decisions.",
            styles["MemoText"],
        ),
        Paragraph("<b>Limitations</b>", styles["Heading2"]),
        Paragraph(
            "This is historical observational data. Payment totals may not "
            "reconcile to item and freight totals for some orders. Payment "
            "revenue is not necessarily recognized accounting revenue, and "
            "delivery/review associations are descriptive rather than causal.",
            styles["SmallText"],
        ),
    ])

    # --------------------------------------------------
    # Write the PDF
    # --------------------------------------------------

    pdf_path = OUT / "weekly_business_review.pdf"

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="Weekly Business Review — Olist E-commerce",
    )

    doc.build(story)

    print("Report generated:", pdf_path)
    print("Charts generated in reports/")
    print("On-time delivery rate:", pct(on_time_rate))
    print("Late delivery rate:", pct(late_rate))
    print(f"Average review score: {avg_review:.2f}/5")
    print("Repeat-purchase rate:", pct(repeat_rate))
    print("Review the report and validate all findings before submission.")

finally:
    engine.dispose()

