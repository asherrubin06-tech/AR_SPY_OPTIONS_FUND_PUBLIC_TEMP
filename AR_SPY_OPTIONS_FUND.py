import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime
import calendar
import json
import os
from twilio.rest import Client

st.set_page_config(page_title="AR SPY Options Fund", layout="wide")

# ---------------------------
# 1️⃣ Password protection
# ---------------------------
PASSWORD = "Mag_Ash88922"  # Change this
st.title("AR SPY Options Fund")

password_input = st.text_input("Enter password:", type="password")
if password_input != PASSWORD:
    st.warning("Incorrect password")
    st.stop()

# ---------------------------
# 2️⃣ Load SPY data
# ---------------------------
today_dt = datetime.today()
spy = yf.Ticker("SPY")

# --- Historical 5-year data ---
start_5y = today_dt - pd.DateOffset(years=5)
df5y = spy.history(start=start_5y, end=today_dt, interval="1d")
df5y['SMA5'] = df5y['Close'].rolling(5).mean()
df5y['SMA20'] = df5y['Close'].rolling(20).mean()
df5y['SMA50'] = df5y['Close'].rolling(50).mean()
df5y['Weekday'] = df5y.index.weekday

# --- YTD data ---
start_ytd = datetime(today_dt.year, 1, 1)
df_ytd = spy.history(start=start_ytd, end=today_dt, interval="1d")
df_ytd['SMA5'] = df_ytd['Close'].rolling(5).mean()
df_ytd['SMA20'] = df_ytd['Close'].rolling(20).mean()
df_ytd['SMA50'] = df_ytd['Close'].rolling(50).mean()
df_ytd['Weekday'] = df_ytd.index.weekday

# ---------------------------
# 3️⃣ Generate trades (40x strategy)
# ---------------------------
def generate_trades(df, leverage=True):
    fridays = df[df['Weekday'] == 4].index
    trades = []
    capital = 1
    for date in fridays:
        today_row = df.loc[date]
        pos = 0
        if today_row['SMA20'] > today_row['SMA50'] and today_row['SMA5'] > today_row['SMA20']:
            pos = 1
            position_name = "Bullish Call"
            lev = 3
        elif today_row['SMA20'] < today_row['SMA50'] and today_row['SMA5'] < today_row['SMA20']:
            pos = -1
            position_name = "Bearish Put"
            lev = 3
        else:
            pos = 2
            position_name = "Straddle"
            lev = 2

        if pos != 0:
            start_idx = df.index.get_loc(date)
            end_idx = min(start_idx + 5, len(df)-1)
            entry_price = df['Close'].iloc[start_idx]
            exit_price = df['Close'].iloc[end_idx]

            if pos == 1:
                weekly_return = (exit_price / entry_price - 1)
            elif pos == -1:
                weekly_return = (entry_price / exit_price - 1)
            else:
                weekly_return = abs(exit_price / entry_price - 1)

            if leverage:
                weekly_return *= lev

            capital *= (1 + weekly_return)
            trades.append({
                'Date': date,
                'Position': position_name,
                'Entry Price': entry_price,
                'Exit Price': exit_price,
                'Return': weekly_return,
                'Cumulative': capital
            })
    trades_df = pd.DataFrame(trades)
    trades_df['Month'] = trades_df['Date'].dt.month
    trades_df['Week'] = trades_df['Date'].dt.isocalendar().week
    return trades_df

trades_5y = generate_trades(df5y, leverage=True)
trades_ytd = generate_trades(df_ytd, leverage=False)

total_return_5y = trades_5y['Cumulative'].iloc[-1] - 1
total_return_ytd = trades_ytd['Cumulative'].iloc[-1] - 1

# ---------------------------
# 4️⃣ Sidebar metrics
# ---------------------------
st.sidebar.metric("5-Year Strategy Return", f"{total_return_5y*100:.2f}%")
st.sidebar.metric("YTD Return", f"{total_return_ytd*100:.2f}%")

# ---------------------------
# 5️⃣ Current week trade (Monday lock)
# ---------------------------
CACHE_FILE = "current_week_trade.json"

def get_current_week_trade(send_sms=False):
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            cache = json.load(f)
        if cache.get("week") == today_dt.isocalendar()[1]:
            return cache["trade"]

    # Find all Fridays in YTD
    fridays = df_ytd[df_ytd['Weekday'] == 4].index
    if len(fridays) == 0:
        return None

    # Pick the last trading Friday
    last_friday = pd.to_datetime(fridays[-1]).tz_localize(None)

    # Use closest date in df_ytd in case of mismatch
    closest_idx = df_ytd.index.get_indexer([last_friday], method='nearest')[0]
    today_row = df_ytd.iloc[closest_idx]
    last_friday = df_ytd.index[closest_idx]

    # Determine position
    if today_row['SMA20'] > today_row['SMA50'] and today_row['SMA5'] > today_row['SMA20']:
        position_name = "Bullish Call"
    elif today_row['SMA20'] < today_row['SMA50'] and today_row['SMA5'] < today_row['SMA20']:
        position_name = "Bearish Put"
    else:
        position_name = "Straddle"

    atm_strike = ''
    option_price = ''
    tp = ''
    sl = ''

    exp_dates = [pd.to_datetime(d).tz_localize(None) for d in spy.options]
    if exp_dates:
        expiration = min(exp_dates, key=lambda d: abs((d - last_friday).days))
        options_chain = spy.option_chain(expiration.strftime("%Y-%m-%d"))
        current_price = today_row['Close']
        atm_strike = min(options_chain.calls['strike'].tolist(), key=lambda x: abs(x - current_price))
        if position_name == "Bullish Call":
            option_price = options_chain.calls[options_chain.calls['strike'] == atm_strike]['lastPrice'].iloc[0]
            tp = option_price * 1.1
            sl = option_price * 0.95
        elif position_name == "Bearish Put":
            option_price = options_chain.puts[options_chain.puts['strike'] == atm_strike]['lastPrice'].iloc[0]
            tp = option_price * 1.1
            sl = option_price * 0.95

    trade = {
        "Date": str(last_friday.date()),
        "Position": position_name,
        "ATM Strike": atm_strike,
        "Option Price": option_price,
        "TP": tp,
        "SL": sl
    }

    # Cache for the week
    cache_data = {"week": today_dt.isocalendar()[1], "trade": trade}
    with open(CACHE_FILE, "w") as f:
        json.dump(cache_data, f)

    return trade

current_trade = get_current_week_trade(send_sms=False)

st.subheader("Current Week Trade (Locked Monday Morning)")
if current_trade:
    st.markdown(f"**Position:** {current_trade['Position']}")
    st.markdown(f"**Entry Date (last Friday):** {current_trade['Date']}")
    if current_trade['Position'] != "Straddle":
        st.markdown(f"**ATM Strike:** ${current_trade['ATM Strike']}")
        st.markdown(f"**Option Price:** ${current_trade['Option Price']:.2f}")
        st.markdown(f"**TP:** ${current_trade['TP']:.2f} | **SL:** ${current_trade['SL']:.2f}")
else:
    st.write("No trade recommendation available for this week.")

# ---------------------------
# 6️⃣ Monthly calendar view
# ---------------------------
st.subheader("Monthly Trades YTD 2026")
for month in range(1, 13):
    month_name = calendar.month_name[month]
    st.markdown(f"### {month_name}")
    month_trades = trades_ytd[trades_ytd['Month'] == month]
    if not month_trades.empty:
        display_cols = ['Date', 'Position', 'Entry Price', 'Exit Price', 'Return']
        month_trades_display = month_trades[display_cols]
        month_trades_display['Current Week'] = month_trades_display['Date'].apply(
            lambda d: "✅" if d.isocalendar()[1] == today_dt.isocalendar()[1] else ""
        )
        st.dataframe(month_trades_display.style.format({"Return": "{:.2%}"}))
    else:
        st.write("No trades this month.")

