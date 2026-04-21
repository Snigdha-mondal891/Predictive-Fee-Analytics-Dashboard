#![no_std]

use soroban_sdk::{
    contract, contractimpl, contracttype, symbol_short, Address, Env, Map, Symbol, Vec,
};

// ──────────────────────────────────────────────────────────────────────────────
// Data Types
// ──────────────────────────────────────────────────────────────────────────────

/// Status of a registered batch.
#[contracttype]
#[derive(Clone, Debug, PartialEq)]
pub enum BatchStatus {
    Pending,
    Executed,
    Cancelled,
}

/// A single batch record stored on‑chain.
#[contracttype]
#[derive(Clone, Debug)]
pub struct Batch {
    pub id: u64,
    pub owner: Address,
    pub tx_count: u32,
    pub max_fee_per_tx: u64,
    pub status: BatchStatus,
    pub created_at: u64,
    pub executed_at: u64,
    pub actual_fee: u64,
}

/// Aggregate statistics tracked by the contract.
#[contracttype]
#[derive(Clone, Debug)]
pub struct Stats {
    pub total_batches: u64,
    pub total_executed: u64,
    pub total_cancelled: u64,
    pub total_tx_scheduled: u64,
    pub total_tx_executed: u64,
    pub cumulative_fee_savings: i128,
}

// ──────────────────────────────────────────────────────────────────────────────
// Storage Keys
// ──────────────────────────────────────────────────────────────────────────────

const ADMIN: Symbol = symbol_short!("ADMIN");
const MAX_BATCH: Symbol = symbol_short!("MAXBATCH");
const FEE_THR: Symbol = symbol_short!("FEE_THR");
const NEXT_ID: Symbol = symbol_short!("NEXT_ID");
const STATS: Symbol = symbol_short!("STATS");

/// Helper to build a per‑batch storage key.
fn batch_key(id: u64) -> (Symbol, u64) {
    (symbol_short!("BATCH"), id)
}

/// Helper to build a per‑user batch‑list key.
fn user_key(user: &Address) -> (Symbol, Address) {
    (symbol_short!("USER"), user.clone())
}

// ──────────────────────────────────────────────────────────────────────────────
// Contract
// ──────────────────────────────────────────────────────────────────────────────

#[contract]
pub struct BatchScheduler;

#[contractimpl]
impl BatchScheduler {
    // ── Admin Initialization ─────────────────────────────────────────────

    /// Initialize the contract. Can only be called once.
    ///
    /// * `admin`              – The privileged address allowed to execute batches.
    /// * `max_batch_size`     – Maximum number of transactions in a single batch.
    /// * `base_fee_threshold` – Default fee ceiling (stroops) above which batches wait.
    pub fn initialize(env: Env, admin: Address, max_batch_size: u32, base_fee_threshold: u64) {
        // Prevent re‑initialization
        if env.storage().instance().has(&ADMIN) {
            panic!("already initialized");
        }

        admin.require_auth();

        env.storage().instance().set(&ADMIN, &admin);
        env.storage().instance().set(&MAX_BATCH, &max_batch_size);
        env.storage().instance().set(&FEE_THR, &base_fee_threshold);
        env.storage().instance().set(&NEXT_ID, &1u64);

        let initial_stats = Stats {
            total_batches: 0,
            total_executed: 0,
            total_cancelled: 0,
            total_tx_scheduled: 0,
            total_tx_executed: 0,
            cumulative_fee_savings: 0,
        };
        env.storage().instance().set(&STATS, &initial_stats);

        env.events().publish(
            (symbol_short!("init"),),
            (admin, max_batch_size, base_fee_threshold),
        );
    }

    // ── Batch Lifecycle ──────────────────────────────────────────────────

    /// Register a new pending batch.
    ///
    /// * `user`           – The batch owner (must authorize).
    /// * `tx_count`       – Number of transactions to batch.
    /// * `max_fee_per_tx` – Maximum acceptable fee per transaction (stroops).
    ///
    /// Returns the newly created batch ID.
    pub fn create_batch(env: Env, user: Address, tx_count: u32, max_fee_per_tx: u64) -> u64 {
        user.require_auth();

        let max_batch_size: u32 = env.storage().instance().get(&MAX_BATCH).unwrap();
        if tx_count == 0 || tx_count > max_batch_size {
            panic!("tx_count must be between 1 and max_batch_size");
        }

        let batch_id: u64 = env.storage().instance().get(&NEXT_ID).unwrap();
        env.storage().instance().set(&NEXT_ID, &(batch_id + 1));

        let batch = Batch {
            id: batch_id,
            owner: user.clone(),
            tx_count,
            max_fee_per_tx,
            status: BatchStatus::Pending,
            created_at: env.ledger().timestamp(),
            executed_at: 0,
            actual_fee: 0,
        };

        env.storage().persistent().set(&batch_key(batch_id), &batch);

        // Track batch under user
        let ukey = user_key(&user);
        let mut user_batches: Vec<u64> = env
            .storage()
            .persistent()
            .get(&ukey)
            .unwrap_or(Vec::new(&env));
        user_batches.push_back(batch_id);
        env.storage().persistent().set(&ukey, &user_batches);

        // Update stats
        let mut stats: Stats = env.storage().instance().get(&STATS).unwrap();
        stats.total_batches += 1;
        stats.total_tx_scheduled += tx_count as u64;
        env.storage().instance().set(&STATS, &stats);

        env.events().publish(
            (symbol_short!("create"), user),
            (batch_id, tx_count, max_fee_per_tx),
        );

        batch_id
    }

    /// Execute a pending batch. Only the admin may call this (the off‑chain
    /// service submits transactions and then records execution here).
    ///
    /// * `batch_id`   – The batch to mark as executed.
    /// * `actual_fee` – The actual per‑tx fee paid (stroops).
    pub fn execute_batch(env: Env, batch_id: u64, actual_fee: u64) {
        let admin: Address = env.storage().instance().get(&ADMIN).unwrap();
        admin.require_auth();

        let key = batch_key(batch_id);
        let mut batch: Batch = env
            .storage()
            .persistent()
            .get(&key)
            .expect("batch not found");

        if batch.status != BatchStatus::Pending {
            panic!("batch is not pending");
        }

        batch.status = BatchStatus::Executed;
        batch.executed_at = env.ledger().timestamp();
        batch.actual_fee = actual_fee;
        env.storage().persistent().set(&key, &batch);

        // Calculate savings: (max_fee - actual_fee) * tx_count
        let savings_per_tx = (batch.max_fee_per_tx as i128) - (actual_fee as i128);
        let total_savings = savings_per_tx * (batch.tx_count as i128);

        let mut stats: Stats = env.storage().instance().get(&STATS).unwrap();
        stats.total_executed += 1;
        stats.total_tx_executed += batch.tx_count as u64;
        stats.cumulative_fee_savings += total_savings;
        env.storage().instance().set(&STATS, &stats);

        env.events().publish(
            (symbol_short!("execute"), batch.owner),
            (batch_id, actual_fee, total_savings),
        );
    }

    /// Cancel a pending batch. Only the batch owner may cancel.
    pub fn cancel_batch(env: Env, batch_id: u64) {
        let key = batch_key(batch_id);
        let mut batch: Batch = env
            .storage()
            .persistent()
            .get(&key)
            .expect("batch not found");

        batch.owner.require_auth();

        if batch.status != BatchStatus::Pending {
            panic!("batch is not pending");
        }

        batch.status = BatchStatus::Cancelled;
        env.storage().persistent().set(&key, &batch);

        let mut stats: Stats = env.storage().instance().get(&STATS).unwrap();
        stats.total_cancelled += 1;
        env.storage().instance().set(&STATS, &stats);

        env.events().publish(
            (symbol_short!("cancel"), batch.owner),
            batch_id,
        );
    }

    // ── Queries ──────────────────────────────────────────────────────────

    /// Return batch details by ID.
    pub fn get_batch(env: Env, batch_id: u64) -> Batch {
        env.storage()
            .persistent()
            .get(&batch_key(batch_id))
            .expect("batch not found")
    }

    /// Return all batch IDs for a given user.
    pub fn get_user_batches(env: Env, user: Address) -> Vec<u64> {
        env.storage()
            .persistent()
            .get(&user_key(&user))
            .unwrap_or(Vec::new(&env))
    }

    /// Return global stats.
    pub fn get_stats(env: Env) -> Stats {
        env.storage().instance().get(&STATS).unwrap()
    }

    /// Return the configured fee threshold.
    pub fn get_fee_threshold(env: Env) -> u64 {
        env.storage().instance().get(&FEE_THR).unwrap()
    }

    /// Update the fee threshold. Admin only.
    pub fn set_fee_threshold(env: Env, new_threshold: u64) {
        let admin: Address = env.storage().instance().get(&ADMIN).unwrap();
        admin.require_auth();
        env.storage().instance().set(&FEE_THR, &new_threshold);

        env.events().publish(
            (symbol_short!("cfg"),),
            new_threshold,
        );
    }
}

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod test {
    use super::*;
    use soroban_sdk::testutils::Address as _;
    use soroban_sdk::Env;

    fn setup() -> (Env, Address, Address, BatchSchedulerClient<'static>) {
        let env = Env::default();
        env.mock_all_auths();

        let contract_id = env.register(BatchScheduler, ());
        let client = BatchSchedulerClient::new(&env, &contract_id);

        let admin = Address::generate(&env);
        let user = Address::generate(&env);

        client.initialize(&admin, &500, &200);

        (env, admin, user, client)
    }

    #[test]
    fn test_create_and_get_batch() {
        let (_env, _admin, user, client) = setup();

        let id = client.create_batch(&user, &10, &150);
        assert_eq!(id, 1);

        let batch = client.get_batch(&id);
        assert_eq!(batch.tx_count, 10);
        assert_eq!(batch.max_fee_per_tx, 150);
        assert_eq!(batch.status, BatchStatus::Pending);
        assert_eq!(batch.owner, user);
    }

    #[test]
    fn test_execute_batch_tracks_savings() {
        let (_env, _admin, user, client) = setup();

        let id = client.create_batch(&user, &20, &300);

        // Admin executes with actual fee of 100 stroops
        client.execute_batch(&id, &100);

        let batch = client.get_batch(&id);
        assert_eq!(batch.status, BatchStatus::Executed);
        assert_eq!(batch.actual_fee, 100);

        let stats = client.get_stats();
        assert_eq!(stats.total_executed, 1);
        assert_eq!(stats.total_tx_executed, 20);
        // Savings = (300 - 100) * 20 = 4000
        assert_eq!(stats.cumulative_fee_savings, 4000);
    }

    #[test]
    fn test_cancel_batch() {
        let (_env, _admin, user, client) = setup();

        let id = client.create_batch(&user, &5, &200);
        client.cancel_batch(&id);

        let batch = client.get_batch(&id);
        assert_eq!(batch.status, BatchStatus::Cancelled);

        let stats = client.get_stats();
        assert_eq!(stats.total_cancelled, 1);
    }

    #[test]
    fn test_user_batches_tracking() {
        let (_env, _admin, user, client) = setup();

        let id1 = client.create_batch(&user, &10, &100);
        let id2 = client.create_batch(&user, &20, &200);

        let user_batches = client.get_user_batches(&user);
        assert_eq!(user_batches.len(), 2);
        assert_eq!(user_batches.get(0).unwrap(), id1);
        assert_eq!(user_batches.get(1).unwrap(), id2);
    }

    #[test]
    fn test_stats_aggregate() {
        let (_env, _admin, user, client) = setup();

        client.create_batch(&user, &10, &150);
        client.create_batch(&user, &20, &250);
        client.create_batch(&user, &5, &100);

        let stats = client.get_stats();
        assert_eq!(stats.total_batches, 3);
        assert_eq!(stats.total_tx_scheduled, 35);
    }

    #[test]
    #[should_panic(expected = "already initialized")]
    fn test_double_init_panics() {
        let (_env, admin, _user, client) = setup();
        client.initialize(&admin, &100, &100);
    }

    #[test]
    fn test_update_fee_threshold() {
        let (_env, _admin, _user, client) = setup();

        assert_eq!(client.get_fee_threshold(), 200);
        client.set_fee_threshold(&500);
        assert_eq!(client.get_fee_threshold(), 500);
    }
}
