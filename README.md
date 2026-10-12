# Olist Weekly Business Review

A GitHub-ready starter implementation for the Take-Home Assignment 1. It builds raw tables, staging views, an order-level analytics mart, SQL quality alarms, five analytics queries, charts, and a PDF report.

## Stack
- Python 3.10+
- PostgreSQL 14+
- pandas + SQLAlchemy for ingestion/report preparation
- SQL CTEs and window functions for Part C
- Matplotlib + ReportLab for charts and PDF

## 1. Download the dataset
Download the Brazilian E-Commerce Public Dataset by Olist from Kaggle:
https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

Extract the CSV files into `data/raw/`. Required files:
- `olist_orders_dataset.csv`
- `olist_order_items_dataset.csv`
- `olist_order_payments_dataset.csv`
- `olist_order_reviews_dataset.csv`
- `olist_customers_dataset.csv`
- `olist_products_dataset.csv`

The pipeline deliberately fails with a clear message if any required file/column is missing. Seller and geolocation CSVs are not needed for the current analysis questions.

## 2. Create a PostgreSQL database
Example in `psql`:
```sql
CREATE DATABASE olist_analytics;
```
Install PostgreSQL and ensure the database service is running.

## 3. Configure Python
Windows Command Prompt:
```bat
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```
Edit `.env` and set `DATABASE_URL` with your PostgreSQL username/password. Example:
`postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/olist_analytics`

## 4. Run the pipeline
From the project root:
```bat
python src/pipeline.py
```
The pipeline fully replaces raw tables each run (idempotent), recreates staging views and the mart, logs each step to console and `pipeline.log`, and raises a `DATA QUALITY ALARM` if checks fail.

## 5. Run Part C queries
Open each file under `sql/analytics/` in pgAdmin Query Tool or `psql`, and execute it after the pipeline succeeds. Save result screenshots or export results for your report. These queries use PostgreSQL syntax, including `DATE_TRUNC`, `FILTER`, and `generate_series`.

## 6. Generate charts and PDF report
```bat
python src/report.py
```
Outputs are written to `reports/`. The report generator uses the actual database contents. Read the generated report and replace generic recommendation language with the observed values before submission.

## Data model
- `raw_*`: raw imported CSV tables.
- `stg_*`: typed/cleaned views.
- `mart_order_summary`: one row per order, with item totals, freight, payment totals, customer state, delivery delay, and average review score.

## Design decisions
- **Idempotency:** raw tables are replaced on each run; staging views and mart are recreated. Re-running does not append duplicate records.
- **Avoiding double counting:** order items, payments, and reviews are aggregated separately to order grain before being joined into the mart.
- **Repeat customer identity:** `customer_unique_id` identifies a customer across multiple order-specific `customer_id` values.
- **Quality policy:** failing rows are counted and logged; pipeline stops instead of silently discarding records. Investigate failures and document any approved remediation.
- **Metric definitions:** revenue is total payment value by purchase month; category revenue is item price excluding freight; the North Star is on-time delivered order rate.

## Important before submission
1. Run the pipeline and fix any errors.
2. Inspect the counts from each quality check and decide whether the data issue is a genuine defect or an expected dataset characteristic. Document counts and remediation.
3. Execute all five SQL queries and inspect their outputs.
4. Generate the report and replace the VP memo's generic language with actual query evidence.
5. Commit code, SQL, README, and report to your GitHub repository. Do not upload Kaggle data files unless you have checked the dataset's license and repository policy.
