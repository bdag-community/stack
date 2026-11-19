#!/usr/bin/env python3

import pathlib
import sys
import unittest

OPS_DIR = pathlib.Path(__file__).resolve().parents[1]
ROOT_DIR = OPS_DIR.parent
sys.path.insert(0, str(OPS_DIR))

import pool_ops  # noqa: E402


class DeploymentPortabilityTests(unittest.TestCase):
    def test_node_child_detection_accepts_packaged_binary_name(self) -> None:
        top = """UID PID PPID C STIME TTY TIME CMD
root 1 0 0 07:45 ? 00:00:00 runuser -u bdagStack -g bdagStack -- /usr/local/bin/nodeworker
dnsmasq 64 55 0 07:45 ? 00:00:00 /usr/local/bin/blockdag-node --configfile /etc/bdagStack/node.conf
"""

        self.assertTrue(pool_ops.bdag_child_running_from_top(top))

    def test_node_child_detection_accepts_rosetta_wrapped_packaged_binary(self) -> None:
        top = """UID PID PPID C STIME TTY TIME CMD
root 41658 41563 0 16:41 ? 00:00:00 /run/rosetta/rosetta /usr/sbin/runuser runuser -u bdagStack -g bdagStack -- /usr/local/bin/nodeworker --node-binary=/usr/local/bin/blockdag-node
999 41917 41658 0 16:41 ? 00:00:02 /run/rosetta/rosetta /usr/local/bin/nodeworker /usr/local/bin/nodeworker --node-binary=/usr/local/bin/blockdag-node
999 41954 41917 99 16:41 ? 00:04:52 /run/rosetta/rosetta /usr/local/bin/blockdag-node /usr/local/bin/blockdag-node --configfile /etc/bdagStack/node.conf
"""

        self.assertTrue(pool_ops.bdag_child_running_from_top(top))

    def test_node_child_detection_keeps_legacy_bdag_binary_name(self) -> None:
        top = """UID PID PPID C STIME TTY TIME CMD
bdag 64 55 0 07:45 ? 00:00:00 /usr/local/bin/bdag --configfile /etc/bdagStack/node.conf
"""

        self.assertTrue(pool_ops.bdag_child_running_from_top(top))

    def test_node_child_detection_does_not_count_wrapper_only(self) -> None:
        top = """UID PID PPID C STIME TTY TIME CMD
root 1 0 0 07:45 ? 00:00:00 runuser -u bdagStack -g bdagStack -- /usr/local/bin/nodeworker
dnsmasq 55 1 0 07:45 ? 00:00:00 /usr/local/bin/nodeworker --node-binary=/usr/local/bin/blockdag-node
"""

        self.assertFalse(pool_ops.bdag_child_running_from_top(top))

    def test_node_child_detection_does_not_count_rosetta_wrapped_wrapper_only(self) -> None:
        top = """UID PID PPID C STIME TTY TIME CMD
root 41658 41563 0 16:41 ? 00:00:00 /run/rosetta/rosetta /usr/sbin/runuser runuser -u bdagStack -g bdagStack -- /usr/local/bin/nodeworker --node-binary=/usr/local/bin/blockdag-node
999 41917 41658 0 16:41 ? 00:00:02 /run/rosetta/rosetta /usr/local/bin/nodeworker /usr/local/bin/nodeworker --node-binary=/usr/local/bin/blockdag-node
"""

        self.assertFalse(pool_ops.bdag_child_running_from_top(top))

    def test_fetch_text_url_uses_python_http_client_not_host_curl(self) -> None:
        captured: dict[str, object] = {}

        class FakeHeaders:
            def get_content_charset(self) -> str:
                return "utf-8"

        class FakeResponse:
            headers = FakeHeaders()

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b"pool_active_connections 0\n"

        def fake_urlopen(request: object, timeout: float) -> FakeResponse:
            captured["url"] = getattr(request, "full_url", "")
            captured["timeout"] = timeout
            return FakeResponse()

        def forbidden_subprocess_run(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("fetch_text_url must not require host curl")

        old_urlopen = pool_ops.urllib.request.urlopen
        old_run = pool_ops.subprocess.run
        try:
            pool_ops.urllib.request.urlopen = fake_urlopen
            pool_ops.subprocess.run = forbidden_subprocess_run
            text = pool_ops.fetch_text_url("http://127.0.0.1:9090/metrics", {"accept": "text/plain"}, timeout=2.5)
        finally:
            pool_ops.urllib.request.urlopen = old_urlopen
            pool_ops.subprocess.run = old_run

        self.assertEqual(text, "pool_active_connections 0\n")
        self.assertEqual(captured["url"], "http://127.0.0.1:9090/metrics")
        self.assertEqual(captured["timeout"], 2.5)

    def test_compose_dashboard_targets_stack_container_names(self) -> None:
        compose = (ROOT_DIR / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("BDAG_NODE_RPC_URL: ${BDAG_NODE_RPC_URL:-http://127.0.0.1:38131}", compose)
        self.assertIn("BDAG_DASHBOARD_REDIS_ENABLED: ${BDAG_DASHBOARD_REDIS_ENABLED:-1}", compose)
        self.assertIn("BDAG_DASHBOARD_LOG_SOURCE: ${BDAG_DASHBOARD_LOG_SOURCE:-docker}", compose)
        self.assertIn("BDAG_POOL_URL: ${BDAG_POOL_URL:-}", compose)
        self.assertIn("${BDAG_HOST_ARP_TABLE_PATH:-/proc/net/arp}:/host/proc/net/arp:ro", compose)
        self.assertIn("ADDR: ${DASHBOARD_LISTEN:-127.0.0.1:8088}", compose)

    def test_release_runtime_excludes_retired_collector_and_cpu_miner(self) -> None:
        compose = (ROOT_DIR / "docker-compose.yml").read_text(encoding="utf-8")
        dockerfile = (ROOT_DIR / "dockerfile").read_text(encoding="utf-8")
        workflow = (ROOT_DIR / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
        self.assertFalse((ROOT_DIR / "docker" / "entrypoint-collector.sh").exists())
        self.assertFalse((ROOT_DIR / "dockerfile-dev").exists())
        self.assertNotIn("Checkout collector repo", workflow)
        self.assertNotIn("path: src/collector", workflow)
        self.assertNotIn("src/collector/", workflow)
        self.assertNotIn("Release zip is missing collector.py", workflow)
        self.assertNotIn("collector_src:", compose)
        self.assertNotIn("cpu_miner_src:", compose)
        self.assertNotIn("\n  collector:", compose)
        self.assertNotIn("\n  cpu-miner:", compose)
        self.assertNotIn("FROM ops-runtime AS collector", dockerfile)
        self.assertNotIn("COPY --from=collector_src", dockerfile)
        self.assertNotIn("COPY --from=collector-source", dockerfile)
        self.assertNotIn("dashboard2", dockerfile)
        self.assertNotIn("git clone --depth 1", dockerfile)
        self.assertFalse((ROOT_DIR / ".github" / "workflows" / "build-cpu.yml").exists())

    def test_dashboard_image_uses_checked_out_dashboard_context(self) -> None:
        compose = (ROOT_DIR / "docker-compose.yml").read_text(encoding="utf-8")
        dockerfile = (ROOT_DIR / "dockerfile").read_text(encoding="utf-8")

        self.assertIn("dashboard_src: ${DASHBOARD_SRC_CONTEXT:-.}", compose)
        self.assertIn('curl -fsS http://127.0.0.1:8088/ >/dev/null', compose)
        self.assertIn("FROM ubuntu:24.04 AS dashboard", dockerfile)
        self.assertIn("redis-server redis-tools", dockerfile)
        self.assertIn("COPY docker/dashboard-redis.conf /etc/redis/redis.conf", dockerfile)

    def test_redis_dash_release_source_is_not_dashboard2(self) -> None:
        workflow = (ROOT_DIR / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
        agents = (ROOT_DIR / "AGENTS.md").read_text(encoding="utf-8")

        self.assertRegex(workflow, r"DASHBOARD_REPO:.*['\"][^'\"]+/redis-dash['\"]")
        self.assertIn("repository: ${{ env.DASHBOARD_REPO }}", workflow)
        self.assertIn("BlockdagEngineering/node-dashboard", workflow)
        self.assertIn("verify_repo redis-dash src/dashboard/main.go", workflow)
        self.assertIn("verify_repo node-dashboard src/node-dashboard/main.go", workflow)
        self.assertIn("go build -trimpath -o ../../bin/node-dashboard .", workflow)
        self.assertIn("bin/dashboard bin/node-dashboard", workflow)
        self.assertIn("BlockdagEngineering/redis-dash", agents)
        self.assertNotIn("BlockdagEngineering/dashboard2", workflow)

    def test_mainnet_defaults_do_not_fallback_to_test_rpc_auth(self) -> None:
        compose = (ROOT_DIR / "docker-compose.yml").read_text(encoding="utf-8")
        env_example = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")
        node_conf_example = (ROOT_DIR / "node.conf.example").read_text(encoding="utf-8")
        stack_defaults = (ROOT_DIR / "ops" / "config" / "stack-defaults.env").read_text(encoding="utf-8")
        portable_env = (ROOT_DIR / "ops" / "portable.env.example").read_text(encoding="utf-8")

        source_files = [
            ".env.example",
            "node.conf.example",
            "docker-compose.yml",
            "ops/config/stack-defaults.env",
            "ops/portable.env.example",
            "ops/pool_ops.py",
            "ops/node_child_guard.py",
            "scripts/release-readiness-check.py",
        ]
        forbidden = [
            "${NODE_RPC_USER:-test}",
            "${NODE_RPC_PASS:-test}",
            'env.get("NODE_RPC_USER", "test")',
            'env.get("NODE_RPC_PASS", "test")',
            'os.environ.get("NODE_RPC_USER", "test")',
            'os.environ.get("NODE_RPC_PASS", "test")',
            "NODE_RPC_USER=test",
            "NODE_RPC_PASS=test",
            "BDAG_POOL_DB_USER=test",
            "BDAG_POOL_DB_NAME=pool",
            "POSTGRES_USER=test",
            "rpcuser=test",
            "rpcpass=test",
        ]
        for relative in source_files:
            text = (ROOT_DIR / relative).read_text(encoding="utf-8")
            for snippet in forbidden:
                self.assertNotIn(snippet, text, f"{relative} must not contain {snippet}")

        self.assertIn("BDAG_NETWORK=mainnet", env_example)
        self.assertIn("rpcuser=bdag_mainnet_rpc", node_conf_example)
        self.assertIn("rpcpass=change-me-mainnet-rpc-password", node_conf_example)
        self.assertIn("BDAG_NETWORK: ${BDAG_NETWORK:-mainnet}", compose)
        self.assertIn("NODE_RPC_USER:      ${NODE_RPC_USER:-}", compose)
        self.assertIn("NODE_RPC_PASS:      ${NODE_RPC_PASS:-}", compose)
        self.assertIn("BDAG_POOL_DB_USER=bdag_pool", stack_defaults)
        self.assertIn("BDAG_POOL_DB_NAME=bdagpool", stack_defaults)
        self.assertIn("BDAG_POOL_DB_USER=bdag_pool", portable_env)
        self.assertIn("BDAG_POOL_DB_NAME=bdagpool", portable_env)
        self.assertIn("POOL_RPC_ROUTER_EVM_HEAD_GUARD_ENABLED=false", env_example)
        self.assertIn("POOL_RPC_ROUTER_EVM_HEAD_GUARD_ENABLED=false", stack_defaults)
        self.assertIn("POOL_RPC_ROUTER_EVM_HEAD_GUARD_ENABLED=false", portable_env)
        self.assertIn(
            "POOL_RPC_ROUTER_EVM_HEAD_GUARD_ENABLED: ${POOL_RPC_ROUTER_EVM_HEAD_GUARD_ENABLED:-false}",
            compose,
        )

    def test_redis_dash_fast_upgrade_runbook_captures_release_gates(self) -> None:
        runbook = (ROOT_DIR / "docs" / "redis-dash-fast-upgrade-runbook.md").read_text(encoding="utf-8")
        checkpoint = (
            ROOT_DIR
            / "docs"
            / "upgrade-checkpoints"
            / "redis-dash-0-0-1-2026-06-22.md"
        ).read_text(encoding="utf-8")
        agent_notes = (ROOT_DIR / "docs" / "agents" / "redis-dash-upgrade.md").read_text(encoding="utf-8")

        combined = "\n".join([runbook, checkpoint, agent_notes])
        for required in [
            "getTemplateHealth",
            "submit_ready=true",
            "mineable_now=true",
            "p2p_fresh_consensus_peer_count",
            "accepted block submissions",
            "/api/live/global",
            "stale peer",
            "stack_node-data",
            "stack_postgres-data",
            "stack_dashboard-redis",
            "test:test",
            "POOL_RPC_ROUTER_EVM_HEAD_GUARD_ENABLED=false",
            "redis-dash",
        ]:
            self.assertIn(required, combined)

    def test_host_dashboard_env_uses_host_reachable_chain_rpc(self) -> None:
        installer = (ROOT_DIR / "ops" / "install-dashboard.sh").read_text(encoding="utf-8")
        portable_env = (ROOT_DIR / "ops" / "portable.env.example").read_text(encoding="utf-8")

        self.assertIn("BDAG_NODE_RPC_URLS=node=http://127.0.0.1:38131", installer)
        self.assertIn("BDAG_GLOBAL_CHAIN_RPC_URLS=node=http://127.0.0.1:38131", installer)
        self.assertIn("BDAG_NODE_RPC_URLS=node=http://127.0.0.1:38131", portable_env)
        self.assertIn("BDAG_GLOBAL_CHAIN_RPC_URLS=node=http://127.0.0.1:38131", portable_env)
        self.assertNotIn("NODE_RPC_URLS=http://node:38131", portable_env)

    def test_compose_protects_temp_paths_from_overlay_io(self) -> None:
        compose = (ROOT_DIR / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertGreaterEqual(compose.count("/var/tmp:size=${BDAG_CONTAINER_TMPFS_SIZE:-128m},mode=1777"), 3)
        self.assertIn("cpu_shares: 4096", compose)
        self.assertIn("cpu_shares: 3072", compose)
        self.assertIn("cpu_shares: 256", compose)
        self.assertGreaterEqual(compose.count("TMPDIR: /tmp"), 4)
        self.assertGreaterEqual(compose.count("TMP: /tmp"), 4)
        self.assertGreaterEqual(compose.count("TEMP: /tmp"), 4)

    def test_compose_mounts_configured_persistent_data_paths(self) -> None:
        compose = (ROOT_DIR / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("postgres-data:/var/lib/postgresql/data", compose)
        self.assertIn("${NODE_DATA_DIR:-./node-data}:/var/lib/bdagStack/node", compose)
        self.assertIn("nodeworker-data:/var/lib/bdagStack/nodeworker", compose)
        self.assertIn("  postgres-data:", compose)
        self.assertIn("  node-data:", compose)
        self.assertIn("  nodeworker-data:", compose)

    def test_pool_node_health_defaults_live_in_stack_defaults(self) -> None:
        stack_defaults = (ROOT_DIR / "ops" / "config" / "stack-defaults.env").read_text(encoding="utf-8")

        self.assertEqual(1, stack_defaults.count("POOL_RPC_ROUTER_NODE_HEALTH_ENABLED=true"))

    def test_pool_node_health_gate_is_enabled_by_default(self) -> None:
        stack_defaults = (ROOT_DIR / "ops" / "config" / "stack-defaults.env").read_text(encoding="utf-8")
        env_example = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")

        self.assertIn("POOL_RPC_ROUTER_NODE_HEALTH_ENABLED=true", stack_defaults)
        self.assertIn("POOL_RPC_ROUTER_NODE_HEALTH_ENABLED=true", env_example)

    def test_goldshell_server_first_probe_stays_disabled_by_default(self) -> None:
        compose = (ROOT_DIR / "docker-compose.yml").read_text(encoding="utf-8")
        env_example = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")
        stack_defaults = (ROOT_DIR / "ops" / "config" / "stack-defaults.env").read_text(encoding="utf-8")
        runbook = (ROOT_DIR / "docs" / "redis-dash-fast-upgrade-runbook.md").read_text(encoding="utf-8")
        agents = (ROOT_DIR / "AGENTS.md").read_text(encoding="utf-8")
        ops_readme = (ROOT_DIR / "ops" / "README.md").read_text(encoding="utf-8")

        self.assertIn("POOL_STRATUM_SERVER_FIRST_DIFFICULTY_PROBE=false", env_example)
        self.assertIn(
            "POOL_STRATUM_SERVER_FIRST_DIFFICULTY_PROBE: ${POOL_STRATUM_SERVER_FIRST_DIFFICULTY_PROBE:-false}",
            compose,
        )
        self.assertIn("POOL_STRATUM_SERVER_FIRST_DIFFICULTY_PROBE=false", runbook)
        self.assertIn("POOL_STRATUM_SERVER_FIRST_DIFFICULTY_PROBE=false", agents)
        self.assertIn("POOL_STRATUM_SERVER_FIRST_DIFFICULTY_PROBE=false", ops_readme)
        self.assertIn("POOL_STRATUM_SERVER_FIRST_DIFFICULTY_PROBE:-false", compose)
        self.assertIn("POOL_TEMPLATE_TTL_REFRESH_MS=1000", env_example)
        self.assertIn("POOL_TEMPLATE_TTL_REFRESH_MS=1000", stack_defaults)
        self.assertIn("POOL_TEMPLATE_TTL_REFRESH_MS: ${POOL_TEMPLATE_TTL_REFRESH_MS:-1000}", compose)
        self.assertIn("POOL_TEMPLATE_TTL_REFRESH_MS:-1000", compose)
        self.assertIn("POOL_MAX_BLOCK_CANDIDATE_JOB_AGE_MS=2500", env_example)
        self.assertIn("POOL_MAX_BLOCK_CANDIDATE_JOB_AGE_MS=2500", stack_defaults)
        self.assertIn(
            "POOL_MAX_BLOCK_CANDIDATE_JOB_AGE_MS: ${POOL_MAX_BLOCK_CANDIDATE_JOB_AGE_MS:-2500}",
            compose,
        )
        self.assertIn("POOL_MAX_BLOCK_CANDIDATE_JOB_AGE_MS:-2500", compose)

    def test_live_deploy_rollback_validates_manifest_not_new_rc_contract(self) -> None:
        deploy = (ROOT_DIR / "ops" / "deploy-live-runtime-update.sh").read_text(encoding="utf-8")
        rollback_body = deploy.split("rollback_from_backup()", 1)[1].split("if [[ -n \"$ROLLBACK_DIR\" ]]", 1)[0]

        self.assertIn("validate_rollback_restored", deploy)
        self.assertIn("validate_rollback_restored || die", rollback_body)
        self.assertNotIn("run_target_validation", rollback_body)

    def test_installers_pin_pool_host_and_asic_lan_scope(self) -> None:
        env_example = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")
        compose = (ROOT_DIR / "docker-compose.yml").read_text(encoding="utf-8")
        entrypoint = (ROOT_DIR / "docker" / "entrypoint-nodeworker.sh").read_text(encoding="utf-8")
        test_release_deployer = (ROOT_DIR / "scripts" / "local-deploy-test-release.sh").read_text(encoding="utf-8")

        self.assertIn("BDAG_DOCKER_BRIDGE_CIDRS=172.16.0.0/12", env_example)
        self.assertIn("BDAG_ALLOW_DOCKER_BRIDGE_ASIC_IPS=0", env_example)
        self.assertIn("BDAG_ASIC_LAN_CIDRS: ${BDAG_ASIC_LAN_CIDRS:-}", compose)
        self.assertIn("tr ',' ' '", entrypoint)
        self.assertIn('append_node_arg_once "--modules=${word}"', entrypoint)
        self.assertIn("grep -E '^rpcuser=' \"$TARGET_DIR/node.conf\"", test_release_deployer)
        self.assertIn("grep -E '^rpcpass=' \"$TARGET_DIR/node.conf\"", test_release_deployer)

    def test_release_docs_keep_zero_miner_default_invariant(self) -> None:
        agents = (ROOT_DIR / "AGENTS.md").read_text(encoding="utf-8")
        readme = (ROOT_DIR / "README.md").read_text(encoding="utf-8")

        self.assertIn("Fresh installs assume zero miner sources", agents)
        self.assertIn("Fresh installs assume zero miner sources", readme)
        self.assertIn("0..N ASIC or Stratum miners", agents)

    def test_p2p_firewall_uses_single_compose_port(self) -> None:
        env_example = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")
        firewall = (ROOT_DIR / "ops" / "allow-p2p-iptables.sh").read_text(encoding="utf-8")
        installer = (ROOT_DIR / "ops" / "install-p2p-services.sh").read_text(encoding="utf-8")
        unit = (ROOT_DIR / "ops" / "systemd" / "bdag-p2p-firewall.service").read_text(encoding="utf-8")

        combined = "\n".join([env_example, firewall, installer, unit])
        self.assertIn("P2P_PORT=8150", env_example)
        self.assertIn('PORT="${P2P_PORT:-8150}"', firewall)
        self.assertIn("Environment=P2P_PORT=8150", unit)
        self.assertNotIn("BDAG_P2P_PORTS", combined)
        self.assertNotIn("--dports", firewall)


if __name__ == "__main__":
    unittest.main()
