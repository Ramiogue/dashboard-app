import streamlit as st
import streamlit_authenticator as stauth
import pandas as pd
from dateutil import parser as dtparser

st.set_page_config(page_title="Merchant Portal", layout="wide")

# ---------------------------
# Auth config from secrets
# ---------------------------
users_cfg = st.secrets.get("users", {})
cookie_key = st.secrets.get("COOKIE_KEY", "change-me")

creds = {"usernames": {}}
for uname, u in users_cfg.items():
    creds["usernames"][uname] = {
        "name": u["name"],
        "email": u["email"],
        "password": u["password_hash"],  # already bcrypt hashed
    }

authenticator = stauth.Authenticate(
    credentials=creds,
    cookie_name="merchant_portal",
    key=cookie_key,
    cookie_expiry_days=7,
)

name, auth_status, username = authenticator.login("Login", "main")

if auth_status is False:
    st.error("Invalid credentials")
    st.stop()
elif auth_status is None:
    st.info("Please log in.")
    st.stop()

# Logged in
authenticator.logout("Logout", "sidebar")
st.sidebar.write(f"Hello, **{name}**")

merchant_id = users_cfg[username]["merchant_id"]

# ---------------------------
# Load CSV from repo
# ---------------------------
@st.cache_data(ttl=60)
def load_data():
    df = pd.read_csv("data/merchant_data.csv", parse_dates=["date"])
    return df

raw = load_data()

# ---------------------------
# Filter for this merchant
# ---------------------------
if "merchant_id" not in raw.columns:
    st.error("Expected column 'merchant_id' not found in data.")
    st.stop()

df = raw.loc[raw["merchant_id"] == merchant_id].copy()

st.title("📊 Merchant Dashboard")
st.caption(f"Merchant: **{merchant_id}**")

if df.empty:
    st.warning("No rows for this merchant yet.")
    st.stop()

# Ensure numeric types
for col in ["revenue", "orders", "aov"]:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

# --------------------------------
# Sidebar date filter
# --------------------------------
min_date = df["date"].min()
max_date = df["date"].max()
start_date, end_date = st.sidebar.date_input(
    "Date range",
    value=(min_date.date(), max_date.date()),
    min_value=min_date.date(),
    max_value=max_date.date(),
)
mask = (df["date"].dt.date >= start_date) & (df["date"].dt.date <= end_date)
df = df.loc[mask].sort_values("date")

# --------------------------------
# KPIs
# --------------------------------
total_rev = df["revenue"].sum()
total_orders = int(df["orders"].sum()) if "orders" in df.columns else 0
aov_latest = df["aov"].iloc[-1] if "aov" in df.columns and len(df) else None

k1, k2, k3 = st.columns(3)
k1.metric("Total Revenue", f"R {total_rev:,.0f}")
k2.metric("Total Orders", f"{total_orders:,}")
k3.metric("Latest AOV", f"R {aov_latest:,.2f}" if aov_latest is not None else "—")

# --------------------------------
# Visuals
# --------------------------------
df_plot = df.set_index("date").sort_index()
show_cols = [c for c in ["revenue", "orders"] if c in df_plot.columns]

st.subheader("Trends")
if show_cols:
    st.line_chart(df_plot[show_cols])

if "aov" in df_plot.columns:
    st.subheader("Average Order Value")
    st.bar_chart(df_plot[["aov"]])

st.subheader("Raw Data")
st.dataframe(df.reset_index(drop=True))
