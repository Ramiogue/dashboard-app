import streamlit as st
import streamlit_authenticator as stauth
import pandas as pd

st.set_page_config(page_title="Merchant Portal", layout="wide")

# ----- Auth from secrets -----
users_cfg = st.secrets.get("users", {})
cookie_key = st.secrets.get("COOKIE_KEY", "change-me")

creds = {"usernames": {}}
for uname, u in users_cfg.items():
    creds["usernames"][uname] = {
        "name": u["name"],
        "email": u["email"],
        "password": u["password_hash"],
    }

authenticator = stauth.Authenticate(
    credentials=creds,
    cookie_name="merchant_portal",
    key=cookie_key,
    cookie_expiry_days=7,
)

# NOTE: string location works with 0.3.2
name, auth_status, username = authenticator.login("Login", location="main")

if auth_status is False:
    st.error("Invalid credentials"); st.stop()
elif auth_status is None:
    st.info("Please log in."); st.stop()

authenticator.logout("Logout", "sidebar")
st.sidebar.write(f"Hello, **{name}**")

merchant_id = users_cfg[username]["merchant_id"]

@st.cache_data(ttl=60)
def load_data():
    return pd.read_csv("data/merchant_data.csv", parse_dates=["date"])

raw = load_data()

required = {"merchant_id","date"}
if not required.issubset(raw.columns):
    st.error(f"Missing required column(s): {', '.join(sorted(required - set(raw.columns)))}"); st.stop()

df = raw[raw["merchant_id"] == merchant_id].copy()
if df.empty:
    st.warning("No rows for this merchant yet."); st.stop()

for c in ["revenue","orders","aov"]:
    if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce")

df = df.sort_values("date")
min_d, max_d = df["date"].min().date(), df["date"].max().date()
start_d, end_d = st.sidebar.date_input("Date range", value=(min_d, max_d), min_value=min_d, max_value=max_d)
df = df[(df["date"].dt.date >= start_d) & (df["date"].dt.date <= end_d)]

st.title("📊 Merchant Dashboard")
st.caption(f"Merchant: **{merchant_id}**")

k1,k2,k3 = st.columns(3)
k1.metric("Total Revenue", f"R {df.get('revenue', pd.Series([0])).sum():,.0f}")
k2.metric("Total Orders", f"{int(df.get('orders', pd.Series([0])).sum()):,}")
aov_latest = df["aov"].iloc[-1] if "aov" in df.columns and len(df) else None
k3.metric("Latest AOV", f"R {aov_latest:,.2f}" if aov_latest is not None else "—")

df_plot = df.set_index("date")
to_show = [c for c in ["revenue","orders"] if c in df_plot.columns]
st.subheader("Trends")
if to_show: st.line_chart(df_plot[to_show])
if "aov" in df_plot.columns:
    st.subheader("Average Order Value")
    st.bar_chart(df_plot[["aov"]])

st.subheader("Raw Data")
st.dataframe(df.reset_index(drop=True))
