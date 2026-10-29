// =====================================================================
// Power Query (M) for the fraud model, with INCREMENTAL REFRESH on the fact table
//
// Parameters (Home > Manage Parameters):
//   ExportsFolder : Text      e.g. C:\projects\banking-fraud-detection\exports\
//                             or https://raw.githubusercontent.com/shivesh122/banking-fraud-detection/main/exports/
//   RangeStart    : Date/Time  e.g. 01-01-2026 00:00   (names must be exactly RangeStart / RangeEnd)
//   RangeEnd      : Date/Time  e.g. 31-12-2026 00:00
// =====================================================================

// ---------- fnLoadCsv ----------
(fileName as text) as table =>
let
    Path   = ExportsFolder & fileName,
    Raw    = if Text.StartsWith(ExportsFolder, "http") then Web.Contents(Path) else File.Contents(Path),
    Csv    = Csv.Document(Raw, [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Header = Table.PromoteHeaders(Csv, [PromoteAllScalars = true])
in
    Header

// ---------- fact_transactions (incremental refresh) ----------
let
    Source = fnLoadCsv("fact_transactions.csv"),
    Typed  = Table.TransformColumnTypes(Source, {
        {"txn_id", type text}, {"date_key", Int64.Type}, {"txn_time", type datetime}, {"hour", Int64.Type},
        {"customer_key", Int64.Type}, {"merchant_key", Int64.Type}, {"channel", type text}, {"txn_city", type text},
        {"amount", Currency.Type}, {"amount_ratio", type number}, {"txn_count_1h", Int64.Type},
        {"distance_home_km", type number}, {"is_new_device", Int64.Type}, {"anomaly_score", type number},
        {"fraud_probability", type number}, {"is_alert", Int64.Type}, {"is_fraud", Int64.Type},
        {"fraud_type", type text}, {"dataset", type text}}),
    // Incremental refresh filter: one boundary inclusive, the other exclusive, so no row is loaded twice.
    // With SQL Server as the source this filter folds into the WHERE clause and hits the monthly partitions.
    Window = Table.SelectRows(Typed, each [txn_time] >= RangeStart and [txn_time] < RangeEnd),
    Band   = Table.AddColumn(Window, "risk_band", each
                 if [fraud_probability] >= 0.7 then "High" else if [fraud_probability] >= 0.3 then "Medium" else "Low", type text)
in
    Band

// ---------- dim_customer ----------
let
    Source = fnLoadCsv("dim_customer.csv"),
    Typed  = Table.TransformColumnTypes(Source, {{"customer_key", Int64.Type}, {"customer_id", type text},
        {"segment", type text}, {"home_city", type text}, {"account_open_date", type date}})
in
    Typed

// ---------- dim_merchant ----------
let
    Source = fnLoadCsv("dim_merchant.csv"),
    Typed  = Table.TransformColumnTypes(Source, {{"merchant_key", Int64.Type}, {"merchant_id", type text},
        {"category", type text}, {"merchant_city", type text}, {"is_high_risk", Int64.Type}})
in
    Typed

// ---------- dim_date ----------
let
    Source = fnLoadCsv("dim_date.csv"),
    Typed  = Table.TransformColumnTypes(Source, {{"date_key", Int64.Type}, {"full_date", type date}, {"year", Int64.Type},
        {"month", Int64.Type}, {"year_month", type text}, {"week_start", type date}, {"day_of_week", type text}, {"is_weekend", Int64.Type}})
in
    Typed
