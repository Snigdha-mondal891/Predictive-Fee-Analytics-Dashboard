"""
Stellar Service Layer — Bridges the fee analytics dashboard to the Soroban
BatchScheduler contract deployed on the Stellar network.

Provides helpers for:
  • Connecting to Horizon (testnet / mainnet)
  • Funding testnet accounts via Friendbot
  • Invoking the BatchScheduler contract (create / execute / cancel batches)
  • Querying contract state (batch details, stats)
  • Submitting native XLM transactions at the predicted optimal fee
"""

import requests
from stellar_sdk import (
    Keypair,
    Network,
    Server,
    TransactionBuilder,
    Asset,
)
from stellar_sdk import scval
from stellar_sdk.soroban_rpc import SorobanServer
from stellar_sdk.xdr import TransactionMeta
import time


# ── Configuration ────────────────────────────────────────────────────────────

HORIZON_TESTNET = "https://horizon-testnet.stellar.org"
SOROBAN_RPC_TESTNET = "https://soroban-testnet.stellar.org"
FRIENDBOT_URL = "https://friendbot.stellar.org"
NETWORK_PASSPHRASE = Network.TESTNET_NETWORK_PASSPHRASE


class StellarService:
    """High‑level interface to the Stellar network and the BatchScheduler contract."""

    def __init__(self, contract_id: str | None = None):
        self.horizon = Server(HORIZON_TESTNET)
        self.soroban = SorobanServer(SOROBAN_RPC_TESTNET)
        self.contract_id = contract_id
        self.network_passphrase = NETWORK_PASSPHRASE

    # ── Account Helpers ──────────────────────────────────────────────────

    @staticmethod
    def generate_keypair() -> dict:
        """Generate a new Stellar keypair."""
        kp = Keypair.random()
        return {"public_key": kp.public_key, "secret_key": kp.secret}

    @staticmethod
    def fund_testnet_account(public_key: str) -> dict:
        """Fund an account on the Stellar testnet via Friendbot."""
        resp = requests.get(FRIENDBOT_URL, params={"addr": public_key}, timeout=30)
        if resp.status_code == 200:
            return {"status": "funded", "account": public_key}
        return {"status": "error", "detail": resp.text}

    def get_account_balance(self, public_key: str) -> str:
        """Return the native XLM balance for an account."""
        try:
            account = self.horizon.accounts().account_id(public_key).call()
            for balance in account["balances"]:
                if balance["asset_type"] == "native":
                    return balance["balance"]
        except Exception:
            return "0"
        return "0"

    def get_current_base_fee(self) -> int:
        """Fetch the latest ledger's base fee in stroops."""
        try:
            resp = self.horizon.fee_stats().call()
            return int(resp.get("last_ledger_base_fee", 100))
        except Exception:
            return 100

    def get_fee_stats(self) -> dict:
        """Return the full fee_stats from Horizon."""
        try:
            return self.horizon.fee_stats().call()
        except Exception:
            return {}

    # ── Native XLM Payments ──────────────────────────────────────────────

    def submit_payment(
        self,
        sender_secret: str,
        destination: str,
        amount: str,
        fee: int = 100,
        memo: str | None = None,
    ) -> dict:
        """Build, sign, and submit a native XLM payment transaction."""
        sender_kp = Keypair.from_secret(sender_secret)
        sender_account = self.horizon.load_account(sender_kp.public_key)

        builder = TransactionBuilder(
            source_account=sender_account,
            network_passphrase=self.network_passphrase,
            base_fee=fee,
        )
        builder.append_payment_op(
            destination=destination,
            asset=Asset.native(),
            amount=amount,
        )
        if memo:
            builder.add_text_memo(memo)
        builder.set_timeout(120)

        tx = builder.build()
        tx.sign(sender_kp)

        try:
            response = self.horizon.submit_transaction(tx)
            return {
                "status": "success",
                "hash": response["hash"],
                "ledger": response["ledger"],
                "fee_charged": response.get("fee_charged", fee),
            }
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    # ── Batch Transaction Submission ─────────────────────────────────────

    def submit_batch_payments(
        self,
        sender_secret: str,
        destinations: list[dict],
        fee_per_tx: int = 100,
    ) -> list[dict]:
        """
        Submit a batch of XLM payments.

        Parameters
        ----------
        sender_secret : str
            Sender's secret key.
        destinations : list[dict]
            List of {"address": str, "amount": str} dicts.
        fee_per_tx : int
            Fee to set per transaction (stroops).

        Returns
        -------
        list[dict]
            Results for each transaction.
        """
        results = []
        for dest in destinations:
            result = self.submit_payment(
                sender_secret=sender_secret,
                destination=dest["address"],
                amount=dest["amount"],
                fee=fee_per_tx,
                memo=f"batch-{int(time.time())}",
            )
            results.append({**dest, **result})

        return results

    # ── Contract Invocation (Soroban) ────────────────────────────────────

    def invoke_contract(
        self,
        caller_secret: str,
        function_name: str,
        args: list | None = None,
    ) -> dict:
        """
        Invoke a function on the BatchScheduler Soroban contract.

        This is a generic invoker; higher‑level wrappers below are easier to use.
        """
        if not self.contract_id:
            return {"status": "error", "detail": "No contract_id configured"}

        caller_kp = Keypair.from_secret(caller_secret)

        try:
            source_account = self.soroban.load_account(caller_kp.public_key)

            builder = TransactionBuilder(
                source_account=source_account,
                network_passphrase=self.network_passphrase,
                base_fee=100,
            )
            builder.set_timeout(300)
            builder.append_invoke_contract_function_op(
                contract_id=self.contract_id,
                function_name=function_name,
                parameters=args or [],
            )
            tx = builder.build()

            # Simulate
            sim = self.soroban.simulate_transaction(tx)
            if sim.error:
                return {"status": "error", "detail": f"Simulation failed: {sim.error}"}

            # Prepare (inject footprint, fees)
            prepared_tx = self.soroban.prepare_transaction(tx, sim)
            prepared_tx.sign(caller_kp)

            # Submit
            send_response = self.soroban.send_transaction(prepared_tx)

            if send_response.status == "ERROR":
                return {"status": "error", "detail": "Transaction submission failed"}

            # Poll for result
            tx_hash = send_response.hash
            for _ in range(30):
                get_response = self.soroban.get_transaction(tx_hash)
                if get_response.status == "SUCCESS":
                    return {
                        "status": "success",
                        "hash": tx_hash,
                        "ledger": get_response.ledger,
                    }
                elif get_response.status == "FAILED":
                    return {"status": "error", "detail": "Transaction failed on‑chain"}
                time.sleep(1)

            return {"status": "error", "detail": "Transaction timed out"}

        except Exception as e:
            return {"status": "error", "detail": str(e)}

    # ── High‑Level Contract Wrappers ─────────────────────────────────────

    def contract_create_batch(
        self, caller_secret: str, tx_count: int, max_fee_per_tx: int
    ) -> dict:
        """Register a new pending batch on the contract."""
        caller_kp = Keypair.from_secret(caller_secret)
        args = [
            scval.to_address(caller_kp.public_key),
            scval.to_uint32(tx_count),
            scval.to_uint64(max_fee_per_tx),
        ]
        return self.invoke_contract(caller_secret, "create_batch", args)

    def contract_execute_batch(
        self, admin_secret: str, batch_id: int, actual_fee: int
    ) -> dict:
        """Mark a batch as executed (admin only)."""
        args = [
            scval.to_uint64(batch_id),
            scval.to_uint64(actual_fee),
        ]
        return self.invoke_contract(admin_secret, "execute_batch", args)

    def contract_cancel_batch(self, caller_secret: str, batch_id: int) -> dict:
        """Cancel a pending batch."""
        args = [scval.to_uint64(batch_id)]
        return self.invoke_contract(caller_secret, "cancel_batch", args)

    # ── Network Info ─────────────────────────────────────────────────────

    def get_network_info(self) -> dict:
        """Return a snapshot of the current network state."""
        try:
            ledger = self.horizon.ledgers().order(desc=True).limit(1).call()
            latest = ledger["_embedded"]["records"][0]
            fee_stats = self.get_fee_stats()
            return {
                "network": "testnet",
                "latest_ledger": latest["sequence"],
                "base_fee": latest.get("base_fee_in_stroops", 100),
                "protocol_version": latest.get("protocol_version"),
                "fee_stats": fee_stats,
                "contract_id": self.contract_id or "not configured",
            }
        except Exception as e:
            return {"status": "error", "detail": str(e)}
