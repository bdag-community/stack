## Pool wallet and miner payouts

Pool mining uses an installation-specific reward wallet. The pool profile
creates it automatically on first start and reuses it on subsequent starts.
Its private key stays in a restricted local `.env` file; the separate payment
worker uses it to sign payouts. The node and pool receive only the wallet's
public address. Each miner supplies the address that should receive its rewards.

The pool records accepted, weighted shares and distributes eligible liquid
block rewards and transaction fees in proportion to the work in its PPLNS
window, after the configured pool fee. Payments wait for native-chain maturity
and a ready, verified chain. Locked staking rewards are not part of the liquid
distribution, and payout transactions incur network fees. The worker records
payment attempts and reconciles confirmations to avoid paying a credit twice
after a restart or an ambiguous RPC response. It can send the next payment
once the earlier transaction is included; each credit is marked paid only
after its transaction reaches the required confirmation depth.

If a recorded reward changes position in the DAG, its payout is held until the
pool can verify the current chain evidence. Other eligible rewards continue to
be processed, and each EVM reward can be claimed only once.

The dashboard's Global tab shows the pool's total ASIC hashpower when fresh
telemetry covers the pool; it labels the result as observed when telemetry is
incomplete.

Keep the wallet private key in a restricted local configuration file and in a
protected backup. Never include the key in release artifacts, logs, source
control, or release notes. Losing the key can make wallet funds unrecoverable.

Existing accounting records and credits are preserved during an upgrade. The
schema initializer holds a populated legacy ledger for explicit review and
upgrade. Automatic ASIC reboot operations are disabled in the default pool
profile; the separate `minerops` profile must be enabled to use them.
