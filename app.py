import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os

from src.batching_optimizer import BatchingOptimizer
from src.stellar_service import StellarService

st.set_page_config(page_title="Stellar Fee Analyzer", page_icon="🌠", layout="wide")

# ── Modern Aesthetics via CSS ────────────────────────────────────────────────

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    .reportview-container, .main { background: #0e1117; color: #e0e0e0; font-family: 'Inter', sans-serif; }
    h1, h2, h3 { font-family: 'Inter', sans-serif; color: #00d2ff; }
    
    .stButton>button {
        border: 2px solid #00d2ff; border-radius: 8px; font-weight: bold;
        transition: all 0.3s ease;
    }
    .stButton>button:hover { background-color: #00d2ff; color: #000; transform: translateY(-1px); }
    
    .metric-card {
        background: linear-gradient(135deg, #1e2130 0%, #262a3d 100%);
        padding: 20px; border-radius: 12px; text-align: center;
        border: 1px solid #30364d; transition: transform 0.2s ease;
    }
    .metric-card:hover { transform: translateY(-2px); }
    
    .status-badge {
        display: inline-block; padding: 4px 12px; border-radius: 20px;
        font-size: 0.85rem; font-weight: 600;
    }
    .badge-connected { background: rgba(0, 210, 100, 0.2); color: #00d264; border: 1px solid #00d264; }
    .badge-disconnected { background: rgba(255, 80, 80, 0.2); color: #ff5050; border: 1px solid #ff5050; }
    
    .contract-card {
        background: linear-gradient(135deg, #141829 0%, #1a1f35 100%);
        border: 1px solid #2a3050; border-radius: 12px; padding: 24px; margin: 8px 0;
    }
    
    .section-divider {
        height: 2px;
        background: linear-gradient(90deg, transparent, #00d2ff, transparent);
        margin: 24px 0; border: none;
    }
</style>
""", unsafe_allow_html=True)

st.title("🌠 Stellar Predictive Fee Analyzer")
st.markdown("### Optimize Transaction Batching on the Stellar Network with On‑Chain Scheduling")

# ── Session State Defaults ───────────────────────────────────────────────────

if "stellar_service" not in st.session_state:
    st.session_state.stellar_service = StellarService()
if "wallet_connected" not in st.session_state:
    st.session_state.wallet_connected = False
if "public_key" not in st.session_state:
    st.session_state.public_key = ""
if "secret_key" not in st.session_state:
    st.session_state.secret_key = ""

svc: StellarService = st.session_state.stellar_service

# ── Sidebar — Wallet & Network ───────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🔗 Stellar Wallet")

    if st.session_state.wallet_connected:
        st.markdown(
            '<span class="status-badge badge-connected">● Connected</span>',
            unsafe_allow_html=True,
        )
        st.code(st.session_state.public_key[:12] + "…" + st.session_state.public_key[-6:])
        balance = svc.get_account_balance(st.session_state.public_key)
        st.metric("XLM Balance", f"{balance} XLM")

        if st.button("Disconnect Wallet"):
            st.session_state.wallet_connected = False
            st.session_state.public_key = ""
            st.session_state.secret_key = ""
            st.rerun()
    else:
        st.markdown(
            '<span class="status-badge badge-disconnected">● Disconnected</span>',
            unsafe_allow_html=True,
        )
        tab_import, tab_generate = st.tabs(["Import Key", "Generate New"])

        with tab_import:
            secret_input = st.text_input("Stellar Secret Key", type="password", key="import_secret")
            if st.button("Connect", key="btn_connect_import"):
                if secret_input:
                    try:
                        from stellar_sdk import Keypair
                        kp = Keypair.from_secret(secret_input)
                        st.session_state.public_key = kp.public_key
                        st.session_state.secret_key = secret_input
                        st.session_state.wallet_connected = True
                        st.rerun()
                    except Exception as e:
                        st.error(f"Invalid key: {e}")

        with tab_generate:
            if st.button("Generate Testnet Keypair"):
                kp = StellarService.generate_keypair()
                fund_result = StellarService.fund_testnet_account(kp["public_key"])
                if fund_result["status"] == "funded":
                    st.session_state.public_key = kp["public_key"]
                    st.session_state.secret_key = kp["secret_key"]
                    st.session_state.wallet_connected = True
                    st.success("Keypair generated & funded on testnet!")
                    st.code(f"Public:  {kp['public_key']}\nSecret:  {kp['secret_key']}")
                    st.warning("⚠️ Save your secret key! It won't be shown again.")
                    st.rerun()
                else:
                    st.error(f"Friendbot error: {fund_result.get('detail', 'unknown')}")

    st.markdown("---")
    st.markdown("## 📡 Network Status")
    try:
        net_info = svc.get_network_info()
        if "error" not in net_info.get("status", ""):
            st.metric("Network", "Stellar Testnet")
            st.metric("Latest Ledger", f"#{net_info.get('latest_ledger', 'N/A')}")
            st.metric("Base Fee", f"{net_info.get('base_fee', 100)} stroops")
            st.metric("Contract", net_info.get("contract_id", "—")[:16] + "…" if net_info.get("contract_id", "—") != "not configured" else "Not deployed")
        else:
            st.warning("Could not reach Horizon")
    except Exception:
        st.info("Network info unavailable")

    st.markdown("---")
    contract_id_input = st.text_input("BatchScheduler Contract ID", value=st.session_state.stellar_service.contract_id or "")
    if st.button("Set Contract ID"):
        st.session_state.stellar_service.contract_id = contract_id_input or None
        st.success("Contract ID updated")


# ── Load Historical Data ─────────────────────────────────────────────────────

@st.cache_data
def load_data():
    if os.path.exists("data/historical_fees.csv"):
        df = pd.read_csv("data/historical_fees.csv")
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df
    return pd.DataFrame()

df = load_data()

if df.empty:
    st.warning("Historical data not found. Run `python -m src.data_ingestion` first.")
    st.stop()

# ── Section 1: Fee Trends ────────────────────────────────────────────────────

st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("📈 Historical & Predicted Fee Trend")
    recent_df = df.tail(100).copy()
    fig = px.line(
        recent_df,
        x="timestamp",
        y="max_fee_bid",
        title="Max Fee Bid (Surge Pricing Included)",
        labels={"max_fee_bid": "Fee (Stroops)", "timestamp": "Time"},
        template="plotly_dark",
    )
    fig.update_traces(line_color="#00d2ff")
    fig.update_layout(paper_bgcolor="#0e1117", plot_bgcolor="#141829")
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("🗓️ Weekly Fee Heatmap")
    df["hour_only"] = df["timestamp"].dt.hour
    heatmap_data = df.groupby(["day_of_week", "hour_only"])["max_fee_bid"].mean().reset_index()
    days = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    heatmap_data["day_name"] = heatmap_data["day_of_week"].map(days)

    pivot = heatmap_data.pivot(index="day_name", columns="hour_only", values="max_fee_bid")
    pivot = pivot.reindex(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])

    fig_heat = px.imshow(
        pivot,
        labels=dict(x="Hour of Day (UTC)", y="Day of Week", color="Avg Fee"),
        x=pivot.columns,
        y=pivot.index,
        color_continuous_scale="Viridis",
        aspect="auto",
        template="plotly_dark",
    )
    fig_heat.update_layout(paper_bgcolor="#0e1117", plot_bgcolor="#141829")
    st.plotly_chart(fig_heat, use_container_width=True)

# ── Section 2: Batching Optimizer ────────────────────────────────────────────

st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
st.subheader("⚡ Batching Optimizer")
st.markdown("Determine the optimal time to submit your pending transaction batches using XGBoost forecasting.")

opt_col1, opt_col2 = st.columns([1, 1])

with opt_col1:
    tx_count = st.number_input(
        "Number of pending transactions to batch:",
        min_value=1, max_value=1000, value=50,
    )
    wait_time = st.slider(
        "Max acceptable wait time (minutes):",
        min_value=10, max_value=360, value=120, step=10,
    )

    if st.button("🔍 Calculate Optimal Submission Time"):
        try:
            optimizer = BatchingOptimizer()
            txs_mock = list(range(tx_count))
            res = optimizer.find_optimal_batch_time(txs_mock, wait_time)
            st.session_state["opt_res"] = res
            st.session_state["current_fee"] = df["max_fee_bid"].iloc[-1]
        except Exception as e:
            st.error(f"Forecasting error: {e}. Ensure the model is trained (`python -m src.ml_model`).")

with opt_col2:
    if "opt_res" in st.session_state:
        res = st.session_state["opt_res"]
        curr_cost = st.session_state["current_fee"] * tx_count
        opt_cost = res["total_estimated_cost"]
        savings = curr_cost - opt_cost

        st.markdown(f"### 🎯 Optimal Submission: **{res['optimal_time'].strftime('%H:%M UTC')}**")

        c1, c2, c3 = st.columns(3)
        c1.metric("Submit NOW Cost", f"{curr_cost:.0f} stroops")
        c2.metric("Wait & Batch Cost", f"{opt_cost:.0f} stroops", delta=f"-{savings:.0f}")
        c3.metric("Predicted Fee/Tx", f"{res['predicted_fee']:.0f}")

# ── Section 3: On-Chain Batch Scheduling ─────────────────────────────────────

st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
st.subheader("📜 On-Chain Batch Scheduling (Soroban Contract)")

if not st.session_state.wallet_connected:
    st.info("🔗 Connect your Stellar wallet in the sidebar to interact with the BatchScheduler contract.")
else:
    st.markdown('<div class="contract-card">', unsafe_allow_html=True)

    action_tab1, action_tab2, action_tab3 = st.tabs(
        ["🆕 Create Batch", "✅ Execute Batch", "❌ Cancel Batch"]
    )

    with action_tab1:
        st.markdown("Register a new pending batch on the BatchScheduler contract.")
        cb_tx_count = st.number_input("Transactions in batch:", min_value=1, max_value=500, value=10, key="cb_tx")
        cb_max_fee = st.number_input(
            "Max fee per tx (stroops):",
            min_value=100, max_value=100000, value=200, key="cb_fee",
        )

        if st.button("📝 Register Batch On‑Chain", key="btn_create_batch"):
            if not svc.contract_id:
                st.warning("Set the BatchScheduler Contract ID in the sidebar first.")
            else:
                with st.spinner("Submitting to Soroban…"):
                    result = svc.contract_create_batch(
                        st.session_state.secret_key, cb_tx_count, cb_max_fee
                    )
                if result["status"] == "success":
                    st.success(f"✅ Batch registered! Tx hash: `{result['hash']}`")
                else:
                    st.error(f"Failed: {result.get('detail', 'unknown error')}")

    with action_tab2:
        st.markdown("Mark a pending batch as executed (admin‑only; called after off‑chain submission).")
        ex_batch_id = st.number_input("Batch ID:", min_value=1, value=1, key="ex_id")
        ex_actual_fee = st.number_input("Actual fee paid (stroops):", min_value=1, value=100, key="ex_fee")

        if st.button("✅ Execute Batch", key="btn_exec_batch"):
            if not svc.contract_id:
                st.warning("Set the BatchScheduler Contract ID in the sidebar first.")
            else:
                with st.spinner("Executing on Soroban…"):
                    result = svc.contract_execute_batch(
                        st.session_state.secret_key, ex_batch_id, ex_actual_fee
                    )
                if result["status"] == "success":
                    st.success(f"✅ Batch #{ex_batch_id} executed! Tx: `{result['hash']}`")
                else:
                    st.error(f"Failed: {result.get('detail', 'unknown error')}")

    with action_tab3:
        st.markdown("Cancel a pending batch you own.")
        cancel_id = st.number_input("Batch ID to cancel:", min_value=1, value=1, key="cancel_id")

        if st.button("❌ Cancel Batch", key="btn_cancel_batch"):
            if not svc.contract_id:
                st.warning("Set the BatchScheduler Contract ID in the sidebar first.")
            else:
                with st.spinner("Cancelling on Soroban…"):
                    result = svc.contract_cancel_batch(
                        st.session_state.secret_key, cancel_id
                    )
                if result["status"] == "success":
                    st.success(f"Batch #{cancel_id} cancelled. Tx: `{result['hash']}`")
                else:
                    st.error(f"Failed: {result.get('detail', 'unknown error')}")

    st.markdown("</div>", unsafe_allow_html=True)

# ── Section 4: Direct Payment ────────────────────────────────────────────────

st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
st.subheader("💸 Direct XLM Payment")

if st.session_state.wallet_connected:
    pay_col1, pay_col2 = st.columns(2)
    with pay_col1:
        dest_address = st.text_input("Destination Address", key="pay_dest")
        pay_amount = st.text_input("Amount (XLM)", value="10", key="pay_amt")
        pay_fee = st.number_input("Fee (stroops)", min_value=100, value=100, key="pay_fee")
    with pay_col2:
        if "opt_res" in st.session_state:
            st.info(
                f"💡 The optimizer predicts a fee valley at "
                f"**{st.session_state['opt_res']['optimal_time'].strftime('%H:%M UTC')}** "
                f"with ~{st.session_state['opt_res']['predicted_fee']:.0f} stroops/tx."
            )

    if st.button("🚀 Submit Payment to Stellar Testnet", key="btn_pay"):
        if not dest_address:
            st.warning("Enter a destination address.")
        else:
            with st.spinner("Submitting to Horizon…"):
                result = svc.submit_payment(
                    sender_secret=st.session_state.secret_key,
                    destination=dest_address,
                    amount=pay_amount,
                    fee=pay_fee,
                )
            if result["status"] == "success":
                st.success(f"✅ Payment sent! Hash: `{result['hash']}` | Ledger: #{result['ledger']}")
            else:
                st.error(f"Payment failed: {result.get('detail', 'unknown')}")
else:
    st.info("🔗 Connect your wallet to send payments.")

# ── Footer ───────────────────────────────────────────────────────────────────

st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
st.markdown(
    """
    <div style="text-align:center; color:#555; padding:16px 0; font-size:0.85rem;">
        Built on <b>Stellar</b> · Soroban Smart Contracts · XGBoost Fee Prediction
        <br/>Predictive Fee Analytics Dashboard © 2026
    </div>
    """,
    unsafe_allow_html=True,
)
