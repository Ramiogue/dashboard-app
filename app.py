import streamlit as st
import pandas as pd
import streamlit_authenticator as stauth
from streamlit_authenticator.utilities import Location  # NEW API enum

st.set_page_config(page_title="Merchant Portal", layout="wide")

# =========================
# Auth from Secrets (add in App → Settings → Secrets)
# =========================
# COOKIE_KEY = "replace_with_random_secret"
# [users."merchant_a"]
# name = "Merchant A"
# email = "a@example.com"
# password_hash = "$2b$12$REPLACE_WITH_BCRYPT_HASH_FOR_A"
# merchant_id = "M001 - Merchant A"   # must match CSV values in "Merchant Number - Business Name"
# [users."merchant_b"]
# name = "Merchant B"
# email = "b@example.com"
# password_hash = "$2b$12$REPLACE_WITH_BCRYPT_HASH_FOR_B"
# merchant_id = "M002 - Merchant B"

users_cfg = st.secrets.get("users", {})
cookie_key = st.secrets.get("COOKIE_KEY", "change-me")

# Build credentials for NEW constructor
creds = {"usernames": {}}
for uname, u in users_cfg.items():
    creds["usernames"][uname] = {
        "name": u["name"],
        "email": u["email"],
        "password": u["password_hash"],  # bcrypt hash
    }

# =========================
# NEW authenticator API (>=0.4.x)
# =========================
authenticator = stauth.Authenticate(
    credentials=creds,
    cookie_name="merchant_portal",
    key=cookie_key,
    cookie_expiry_days=7,
)

# NEW login signature: no form_name; use enum Location
name, auth_status, username = authenticator.login(location=Location.MAIN)

if auth_status is False:
    st.error("Invalid credentials"); st.stop()
elif auth_status is None:
    st.info("Please log in."); st.stop()

authenticator.logout("Logout", "sidebar")
st.sidebar.write(f"Hello, **{name}**")

# Resolve merchant_id (must equal values in CSV column "Merchant Number - Business Name")
try:
    merchant_id = users_cfg[username]["merchant_id"]
except KeyError:
    st.error("Merchant mapping not found for this user. Check Secrets configuration.")
    st.stop()

# =========================
# Load transactions CSV
# =========================
@st.cache_data(ttl=60)
def load_transactions():
    # Try root then /data
    paths = ["sample_merchant_transactions.csv", "data/sample_merchant_transactions.csv"]
    last_err = None
    for p in paths:
        try:
            df = pd.read_csv(p)
            df["__path__"] = p
            return df
        except Exception as e:
            last_err = e
    raise FileNotFoundError(f"Could not read CSV from {paths}. Last error: {last_err}")

tx = load_transactions()

# Validate expected columns
needed = {"Merchant Number - Business Name", "Transaction Date", "Settle Amount"}
missing = needed - set(tx.columns)
if missing:
    st.error(f"Missing required column(s) in CSV: {', '.join(sorted(missing))}")
    st.stop()

# Parse/clean
tx["Transaction Date"] = pd.to_datetime(tx["Transaction Date"], errors="coerce")
tx["Settle Amount"] = pd.to_numeric(tx["Settle Amount"], errors="coerce")
tx["Merchant Number - Business Name"] = tx["Merchant Number - Business Name"].astype(str).str.strip()

# Filter to this merchant
merchant_mask = tx["Merchant Number - Business Name"] == merchant_id
merchant_tx = tx.loc[merchant_mask].copy()
if merchant_tx.empty:
    st.warning(f"No transactions found for merchant: {merchant_id}")
    st.stop()

# Aggregate to daily metrics
daily = (
    merchant_tx
    .groupby(merchant_tx["Transaction Date"].dt.date, dropna=False)
    .agg(revenue=("Settle Amount", "sum"),
         orders=("Settle Amount", "count"))
    .reset_index()
    .rename(columns={"Transaction Date": "date"})
)
# Normalize date
if "date" not in daily.columns:
    daily = daily.rename(columns={daily.columns[0]: "date"})
daily["date"] = pd.to_datetime(daily["date"], errors="coerce")
daily["aov"] = (daily["revenue"] / daily["orders"]).where(daily["orders"] > 0)

if daily["date"].isna().all():
    st.error("All transaction dates failed to parse. Check 'Transaction Date' format.")
    st.stop()

daily = daily.dropna(subset=["date"]).sort_values("date")

# Sidebar date filter
min_date = daily["date"].min().date()
max_date = daily["date"].max().date()
start_date, end_date = st.sidebar.date_input(
    "Date range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)
daily = daily[(daily["date"].dt.date >= start_date) & (daily["date"].dt.date <= end_date)]

# KPIs
st.title("📊 Merchant Dashboard")
st.caption(f"Merchant: **{merchant_id}**  |  Source: `{tx['__path__'].iat[0]}`")

total_rev = float(daily["revenue"].sum()) if not daily.empty else 0.0
total_orders = int(daily["orders"].sum()) if not daily.empty else 0
aov_latest = daily["aov"].iloc[-1] if not daily.empty else None

k1, k2, k3 = st.columns(3)
k1.metric("Total Revenue (Settle)", f"R {total_rev:,.0f}")
k2.metric("Total Orders", f"{total_orders:,}")
k3.metric("Latest AOV", f"R {aov_latest:,.2f}" if pd.notnull(aov_latest) else "—")

# Charts
df_plot = daily.set_index("date")
to_show = [c for c in ["revenue", "orders"] if c in df_plot.columns]

st.subheader("Trends")
if to_show:
    st.line_chart(df_plot[to_show])

if "aov" in df_plot.columns:
    st.subheader("Average Order Value (AOV)")
    st.bar_chart(df_plot[["aov"]])

st.subheader("Daily Aggregated Rows")
st.dataframe(daily.reset_index(drop=True))
