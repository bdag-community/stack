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

Accounting is best effort by default. Historical disputes do not prevent
independent blocks from being submitted. If share records are missing or
conflicting and no ASIC owner can be determined for a verified reward, that
reward remains with the pool operator. Known, verifiable owner credits are
processed separately; incomplete or stale chain evidence is retried.

The dashboard's Global tab shows the pool's total ASIC hashpower when fresh
telemetry covers the pool; it labels the result as observed when telemetry is
incomplete.

The Overview tab shows live node and pool status alongside ASIC performance.
The dashboard displays the BDAG Community release version and includes its UI
script locally, so it does not need a third-party CDN to render. The Logs tab
uses a restricted local proxy for the configured node, pool and dashboard logs;
the dashboard itself no longer has access to Docker's control socket. The
dashboard listens on localhost by default; operators can opt in to LAN access
through `DASHBOARD_LISTEN` or use an authenticated reverse proxy.

Mining runtime controls accept local, non-browser requests only. The optional
dashboard API uses a freshly generated signing key by default; deployments that
set `DASHBOARD_JWT_SECRET` must provide at least 32 bytes. Its in-memory users
and generated signing key are lost when that API restarts. API passwords require
at least eight characters, are stored as hashes in memory, and authentication
attempts are rate limited.

Keep the wallet private key in a restricted local configuration file and in a
protected backup. Never include the key in release artifacts, logs, source
control, or release notes. Losing the key can make wallet funds unrecoverable.

Existing accounting records and credits are preserved during an upgrade. The
schema initializer holds a populated legacy ledger for explicit review and
upgrade. Automatic ASIC reboot operations are disabled in the default pool
profile; the separate `minerops` profile must be enabled to use them.
