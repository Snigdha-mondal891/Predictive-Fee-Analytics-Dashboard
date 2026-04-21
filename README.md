# 🌠 Stellar Predictive Fee Analytics Dashboard

A smart fee prediction and batch optimization platform for the **Stellar Network**, powered by machine‑learning forecasting and secured by a **Soroban smart contract** that records batch schedules and savings on‑chain.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Streamlit Dashboard                     │
│  Fee Trends · Heatmap · Batch Optimizer · Wallet · Payments │
└────────────┬──────────────────────┬─────────────────────────┘
             │                      │
     ┌───────▼────────┐    ┌───────▼────────────┐
     │  XGBoost Model  │    │  Stellar Service   │
     │  Fee Prediction │    │  (stellar‑sdk)     │
     └───────┬─────────┘    └──┬─────────────┬───┘
             │                 │             │
     ┌───────▼─────────┐  ┌───▼────┐  ┌─────▼──────────┐
     │ Historical Data  │  │Horizon │  │ Soroban RPC    │
     │ (CSV / Horizon)  │  │  API   │  │ BatchScheduler │
     └──────────────────┘  └────────┘  └────────────────┘
```

### Components

| Component | Path | Description |
|-----------|------|-------------|
| **Dashboard** | `app.py` | Streamlit app with fee visualization, batch optimizer, wallet, and contract interaction |
| **Data Ingestion** | `src/data_ingestion.py` | Fetches Stellar ledger data from Horizon and synthesizes training data |
| **ML Model** | `src/ml_model.py` | XGBoost regressor trained on historical fee patterns |
| **Batch Optimizer** | `src/batching_optimizer.py` | Iterative forecaster that finds optimal low‑fee submission windows |
| **Stellar Service** | `src/stellar_service.py` | Python SDK bridge — payments, Soroban contract invocations, account management |
| **Smart Contract** | `smart-contract/` | Rust/Soroban `BatchScheduler` contract for on‑chain batch scheduling |

---

## Smart Contract — `BatchScheduler`

The Soroban contract provides an **immutable on‑chain record** of fee‑optimized batch scheduling.

### Entry Points

| Function | Access | Description |
|----------|--------|-------------|
| `initialize(admin, max_batch_size, base_fee_threshold)` | Admin | One‑time setup |
| `create_batch(user, tx_count, max_fee_per_tx)` | User | Register a pending batch with a fee ceiling |
| `execute_batch(batch_id, actual_fee)` | Admin | Record execution and calculate savings |
| `cancel_batch(batch_id)` | Owner | Cancel a pending batch |
| `get_batch(batch_id)` | Any | Query batch details |
| `get_user_batches(user)` | Any | List batch IDs for a user |
| `get_stats()` | Any | Global stats: total batches, executions, cumulative savings |
| `get_fee_threshold()` / `set_fee_threshold(val)` | Any / Admin | Read / update the fee ceiling |

### Build & Deploy

```bash
# Prerequisites: Rust + Soroban CLI
rustup target add wasm32-unknown-unknown
cargo install --locked soroban-cli

# Build
cd smart-contract
cargo build --target wasm32-unknown-unknown --release

# Deploy to testnet
soroban contract deploy \
  --wasm target/wasm32-unknown-unknown/release/batch_scheduler.wasm \
  --network testnet \
  --source <YOUR_SECRET_KEY>

# Initialize
soroban contract invoke \
  --id <CONTRACT_ID> \
  --network testnet \
  --source <YOUR_SECRET_KEY> \
  -- initialize \
  --admin <YOUR_PUBLIC_KEY> \
  --max_batch_size 500 \
  --base_fee_threshold 200
```

---

## Getting Started

### 1. Clone & Install

```bash
git clone <repo-url>
cd Predictive-Fee-Analytics-Dashboard
pip install -r requirements.txt
```

### 2. Prepare Training Data

```bash
python -m src.data_ingestion
```

This fetches the latest 1 000 ledgers from Horizon and synthesizes 8 weeks of hourly fee data.

### 3. Train the Model

```bash
python -m src.ml_model
```

Trains an XGBoost regressor and saves it to `models/xgb_fee_model.json`.

### 4. Run the Dashboard

```bash
streamlit run app.py
```

### 5. (Optional) Deploy the Smart Contract

Follow the **Build & Deploy** instructions above, then paste the resulting Contract ID into the dashboard sidebar.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Streamlit, Plotly |
| ML | XGBoost, scikit‑learn, pandas |
| Blockchain SDK | `stellar-sdk` (Python) |
| Smart Contract | Rust + `soroban-sdk` (Soroban) |
| Network | Stellar Testnet (Horizon + Soroban RPC) |

---

## Project Structure

```
Predictive-Fee-Analytics-Dashboard/
├── app.py                          # Streamlit dashboard
├── requirements.txt                # Python dependencies
├── data/
│   └── historical_fees.csv         # Training data (generated)
├── models/
│   └── xgb_fee_model.json          # Trained XGBoost model
├── src/
│   ├── data_ingestion.py           # Horizon data fetcher + synthesizer
│   ├── ml_model.py                 # Model training script
│   ├── batching_optimizer.py       # Fee valley finder
│   └── stellar_service.py          # Stellar / Soroban service layer
└── smart-contract/
    ├── Cargo.toml                  # Rust project manifest
    └── src/
        └── lib.rs                  # BatchScheduler Soroban contract
```

---

## License

MIT
