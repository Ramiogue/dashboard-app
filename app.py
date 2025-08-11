import streamlit as st
import streamlit_authenticator as stauth
import pandas as pd

# ========= App setup =========
st.set_page_config(page_title="Merchant Portal", layout="wide")

# ========= Auth (from Secrets) =========
# In Streamlit Cloud → App → Settings → Secrets, add:
# COOKIE_KEY = "replace_with_random_secret"
# [users."merchant_a"]
# name = "Merchant A"
# email = "a@example.com"
# password_hash = "$2b$12$REPLACE_WITH_BCRYPT_HASH_FOR_A"
# merchant_id = "M001 - Merchant A"
# [users."merchant_b"]
# name = "Merchant B"
# email = "b@example.com"
# password_hash = "$2b$12$REPLACE_WITH_BCRYPT_HASH_FOR_B"
# merchant_id = "M002 - Merchant B"

users_cfg = st.secrets.get("users", {})
cookie_key = st.secrets.get("COOKIE_KEY", "change-me")

# Build 0.3.x-compatible config
config = {
    "credentials": {
        "usernames": {
            uname: {
                "email": u["email"],
                "name": u["name"],
                "password": u["password_hash"],  # bcrypt hash
            }
            for uname, u in users_cfg.items()
        }
    },
    "cookie": {"name": "merchant_portal", "key": cookie_key, "expiry_days": 7},
    "preauthorized": {"emails": []},
}

# Constructor signature for streamlit-authenticator==0.3.2
authenticator = stauth.Authenticate(
    config["credentials"],
    config["cookie"]["name"],
    config["cookie"]["key"],
    config["cookie"]["expiry_days"],
    config["preauthorized"],
)

# Login UI
name, auth_status, username = authenticator.login("Login", location="main")

if auth_status is False:
    st.error("Invalid credentials")
    st.stop()
elif auth_status is None:
    st.info("Please log in.")
    st.stop()

# Logged-in area
authenticator.logout("Logout", "sidebar")
st.sidebar.write(f"Hello, **{name}**")

# Resolve the merchant_id from the secrets mapping (server-side; no user input)
try:
    merchant_id = users_cfg[username]["merchant_id"]
except KeyError:
    st.error("Merchant mapping not found for this user. Check Secrets configuration.")
    st.stop()

# ========= Data load =========
@st.cache_data(ttl=60)
def load_data(path: str) -> pd.DataFrame:
    # Expects columns: merchant_id,date,revenue,orders,aov
    df = pd.read_csv(path, parse_dates=["date"])
    # Coerce numeric fields if present
    for col in ["revenue", "orders", "aov"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df

DATA_PATH = "data/merchant_data.csv"
try:
    raw = load_data(DATA_PATH)
except FileNotFoundError:
    st.error(f"Data file not found at '{DATA_PATH}'. Make sure it exists in your repo.")
    st.stop()

# Basic schema checks
required = {"merchant_id", "date"}
missing = required - set(raw.columns)
if missing:
    st.error(f"Missing required column(s): {', '.join(sorted(missing))}")
    st.stop()

# ========= Filter to this merchant =========
df = raw.loc[raw["merchant_id"] == merchant_id].copy()
if df.empty:
    st.warning("No rows for this merchant yet.")
    st.stop()

df = df.sort_values("date")

# ========= Sidebar filters =========
min_date = df["date"].min().date()
max_date = df["date"].max().date()
start_date, end_date = st.sidebar.date_input(
    "Date range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)
mask = (df["date"].dt.date >= start_date) & (df["date"].dt.date <= end_date)
df = df.loc[mask]

# ========= KPIs =========
total_rev = df["revenue"].sum() if "revenue" in df.columns else 0
total_orders = int(df["orders"].sum()) if "orders" in df.columns else 0
aov_latest = df["aov"].iloc[-1] if "aov" in df.columns and len(df) else None

st.title("📊 Merchant Dashboard")
st.caption(f"Merchant: **{merchant_id}**")

k1, k2, k3 = st.columns(3)
k1.metric("Total Revenue", f"R {total_rev:,.0f}")
k2.metric("Total Orders", f"{total_orders:,}")
k3.metric("Latest AOV", f"R {aov_latest:,.2f}" if aov_latest is not None else "—")

# ========= Visuals =========
df_plot = df.set_index("date")
to_show = [c for c in ["revenue", "orders"] if c in df_plot.columns]

st.subheader("Trends")
if to_show:
    st.line_chart(df_plot[to_show])

if "aov" in df_plot.columns:
    st.subheader("Average Order Value")
    st.bar_chart(df_plot[["aov"]])

st.subheader("Raw Data")
st.dataframe(df.reset_index(drop=True))
