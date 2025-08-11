import streamlit as st
import pandas as pd
import streamlit_authenticator as stauth

st.set_page_config(page_title="Merchant Portal", layout="wide")

# =========================
# Auth from Secrets
# =========================
# Example Secrets (App → Settings → Secrets):
# COOKIE_KEY = "replace_with_random_secret"
# [users."merchant_a"]
# name = "Merchant A"
# email = "a@example.com"
# password_hash = "$2b$12$REPLACE_WITH_BCRYPT_HASH_FOR_A"
# merchant_id = "M001 - Merchant A"   # <-- must match values in the CSV's merchant column
# [users."merchant_b"]
# name = "Merchant B"
# email = "b@example.com"
# password_hash = "$2b$12$REPLACE_WITH_BCRYPT_HASH_FOR_B"
# merchant_id = "M002 - Merchant B"

users_cfg = st.secrets.get("users", {})
cookie_key = st.secrets.get("COOKIE_KEY", "change-me")

# Build credentials dict (new API compatible)
creds = {"usernames": {}}
for uname, u in users_cfg.items():
    creds["usernames"][uname] = {
        "name": u["name"],
        "email": u["email"],
        "password": u["password_hash"],  # bcrypt hash
    }

# =========================
# Authenticator (new API first, fallback to old)
# =========================
def build_authenticator():
    # Try NEW signature (>=0.4.x)
    try:
        return stauth.Authenticate(
            credentials=creds,
            cookie_name="merchant_portal",
            key= cookie_key,
            cookie_expiry_days=7,
        ), "new"
    except TypeError:
        pass
    # Fallback: OLD signature (0.3.x)
    config_03x = {
        "credentials": {"usernames": creds["usernames"]},
        "cookie": {"name": "merchant_portal", "key": cookie_key, "expiry_days": 7},
        "preauthorized": {"emails": []},
    }
    return stauth.Authenticate(
        config_03x["credentials"],
        config_03x["cookie"]["name"],
        config_03x["cookie"]["key"],
        config_03x["cookie"]["expiry_days"],
        config_03x["preauthorized"],
    ), "old"

authenticator, api_mode = build_authenticator()

def do_login():
    if api_mode == "new":
        try:
            from streamlit_authenticator.utilities import Location
            return authenticator.login(location=Location.MAIN)
        except Exception:
            pass
    # Old API positional args: (form_name, location)
    return authenticator.login("Login", "main")

name, auth_status, username = do_login()

if auth_status is False:
    st.error("Invalid credentials"); st.stop()
elif auth_status is None:
    st.info("Please log in."); st.stop()

authenticator.logout("Logout", "sidebar")
st.sidebar.write(f"Hello, **{name}**")

# Resolve merchant_id server-side (must match CSV merchant column values)
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
    # Try repo root, then /data
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

# =========================
# Validate & normalize columns
# =========================
# Expected core columns from your screenshot:
# "Merchant Number - Business Name", "Transaction Date", "Settle Amount"
needed = {
    "Merchant Number - Business Name",
    "Transaction Date",
    "Settle Amount",
}
missing = needed - set(tx.columns)
if missing:
    st.error(f"Missing required column(s) in CSV: {', '.join(sorted(missing))}")
    st.stop()

# Parse date; coerce numeric amount
tx["Transaction Date"] = pd.to_datetime(tx["Transaction Date"], errors="coerce")
tx["Settle Amount"] = pd.to_numeric(tx["Settle Amount"], errors="coerce")

# Optional: clean merchant name (strip spaces)
tx["Merchant Number - Business Name"] = tx["Merchant Number - Business Name"].astype(str).str.strip()

# =========================
# Filter to logged-in merchant
# NOTE: Your Secrets' merchant_id must equal the value in
# "Merchant Number - Business Name" for that merchant.
# Example: "M001 - Merchant A"
# =========================
merchant_mask = tx["Merchant Number - Business Name"] == merchant_id
merchant_tx = tx.loc[merchant_mask].copy()

if merchant_tx.empty:
    st.warning(f"No transactions found for merchant: {merchant_id}")
    st.stop()

# =========================
# Aggregate to daily metrics
# revenue = sum(Settle Amount)
# orders  = count rows
# aov     = revenue / orders
# =========================
daily = (
    merchant_tx
    .groupby(merchant_tx["Transaction Date"].dt.date, dropna=False)
    .agg(revenue=("Settle Amount", "sum"),
         orders=("Settle Amount", "count"))
    .reset_index()
    .rename(columns={"Transaction Date": "date"})
)
daily["date"] = pd.to_datetime(daily["Transaction Date"], errors="coerce") if "Transaction Date" in daily.columns else pd.to_datetime(daily["date"])
daily["aov"] = (daily["revenue"] / daily["orders"]).where(daily["orders"] > 0)

# Guard against no valid dates
if daily["date"].isna().all():
    st.error("All transaction dates are invalid/unparsed. Check the 'Transaction Date' values.")
    st.stop()

daily = daily.dropna(subset=["date"]).sort_values("date")

# =========================
# Sidebar date filter
# =========================
min_date = daily["date"].min().date()
max_date = daily["date"].max().date()
start_date, end_date = st.sidebar.date_input(
    "Date range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)
daily = daily[(daily["date"].dt.date >= start_date) & (daily["date"].dt.date <= end_date)]

# =========================
# KPIs
# =========================
st.title("📊 Merchant Dashboard")
st.caption(f"Merchant: **{merchant_id}**  |  Source: `{tx['__path__'].iat[0]}`")

total_rev = float(daily["revenue"].sum()) if not daily.empty else 0.0
total_orders = int(daily["orders"].sum()) if not daily.empty else 0
aov_latest = daily["aov"].iloc[-1] if not daily.empty else None

k1, k2, k3 = st.columns(3)
k1.metric("Total Revenue (Settle)", f"R {total_rev:,.0f}")
k2.metric("Total Orders", f"{total_orders:,}")
k3.metric("Latest AOV", f"R {aov_latest:,.2f}" if pd.notnull(aov_latest) else "—")

# =========================
# Charts
# =========================
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
