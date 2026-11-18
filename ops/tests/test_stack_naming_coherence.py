#!/usr/bin/env python3

import pathlib
import unittest


ROOT_DIR = pathlib.Path(__file__).resolve().parents[2]


def read(rel: str) -> str:
    return (ROOT_DIR / rel).read_text(encoding="utf-8")


class StackNamingCoherenceTests(unittest.TestCase):
    def test_compose_dashboard_exports_current_container_names(self) -> None:
        compose = read("docker-compose.yml")

        self.assertIn("  pool-db:", compose)
        self.assertIn("  node:", compose)
        self.assertIn("  pool:", compose)
        self.assertIn("container_name: postgres", compose)
        self.assertIn("container_name: node", compose)
        self.assertIn("container_name: pool", compose)
        self.assertIn("BDAG_DASHBOARD_REDIS_ENABLED: ${BDAG_DASHBOARD_REDIS_ENABLED:-1}", compose)
        self.assertIn("BDAG_DASHBOARD_LOG_SOURCE: ${BDAG_DASHBOARD_LOG_SOURCE:-docker}", compose)
        self.assertIn("BDAG_POOL_URL: ${BDAG_POOL_URL:-}", compose)
        self.assertIn("ADDR: ${DASHBOARD_LISTEN:-127.0.0.1:8088}", compose)
        stack_defaults = read("ops/config/stack-defaults.env")
        self.assertIn("BDAG_DASHBOARD_STATUS_CACHE_SECONDS=10", stack_defaults)
        self.assertIn("BDAG_STATUS_PAYLOAD_STALE_AFTER_SECONDS=120", stack_defaults)

    def test_env_examples_use_current_names(self) -> None:
        env_example = read(".env.example")
        portable = read("ops/portable.env.example")

        for text in (env_example, portable):
            self.assertIn("BDAG_POOL_CONTAINER=pool", text)
            self.assertIn("BDAG_POOL_DB_CONTAINER=postgres", text)
            self.assertIn("BDAG_NODE_SERVICES=node", text)
            self.assertIn("BDAG_STACK_SERVICES=postgres,node,pool", text)
            self.assertIn("BDAG_STATUS_PAYLOAD_STALE_AFTER_SECONDS=120", text)
        self.assertIn("POOL_GBT_MIN_INTERVAL_MS=1100", env_example)
        self.assertIn("POOL_GBT_PRESSURE_INTERVAL_MS=500", env_example)
        self.assertIn("POOL_GBT_PRESSURE_WINDOW_SECONDS=10", env_example)
        self.assertIn("POOL_RPC_ROUTER_NODE_HEALTH_PROBE_SECONDS=15", env_example)
        self.assertIn("POOL_RPC_ROUTER_NODE_HEALTH_MAX_AGE_SECONDS=30", env_example)
        self.assertIn("BDAG_CHAIN_PEERSTORE_PEER_EXTRACTION_ENABLED=1", env_example)
        self.assertIn("BDAG_NODE_RPC_URLS=node=http://127.0.0.1:38131", env_example)
        self.assertIn("BDAG_NODE_RPC_URLS=node=http://127.0.0.1:38131", portable)

    def test_watchdogs_default_to_current_names(self) -> None:
        pool_ops = read("ops/pool_ops.py")
        sampler = read("ops/status_sampler.py")
        node_guard = read("ops/node_child_guard.py")
        host_guard = read("host/mining-appliance/bdag-node-child-guard")
        peer_refresh = read("ops/update-local-peers.py")

        self.assertIn('POOL_CONTAINER = os.environ.get("BDAG_POOL_CONTAINER", "pool")', pool_ops)
        self.assertIn('POOL_DB_CONTAINER = os.environ.get("BDAG_POOL_DB_CONTAINER", "postgres")', pool_ops)
        self.assertIn('NODES = split_env_list("BDAG_NODE_SERVICES", "node")', pool_ops)
        self.assertIn('"postgres,node,pool"', pool_ops)
        self.assertIn('config_value("BDAG_NODE_SERVICES", "node")', sampler)
        self.assertIn('DEFAULT_NODE_CHILD_GUARD_NODES = "node"', node_guard)
        self.assertIn('DEFAULT_NODE_CHILD_GUARD_NODES = "node"', host_guard)
        self.assertIn("blockdag-node", node_guard)
        self.assertIn("blockdag-node", host_guard)
        self.assertIn('DEFAULT_ACTIVE_NODE_SERVICES = ["node"]', peer_refresh)

    def test_systemd_watchdogs_share_current_names_and_sampler_defaults(self) -> None:
        root_dashboard = read("ops/systemd/bdag-dashboard.service")
        root_sampler = read("ops/systemd/bdag-status-sampler.service")
        user_dashboard = read("ops/systemd/user-bdag-dashboard.service")
        user_sampler = read("ops/systemd/user-bdag-status-sampler.service")

        for unit in (root_dashboard, root_sampler, user_dashboard, user_sampler):
            self.assertIn("BDAG_NODE_SERVICES=node", unit)
            self.assertIn("BDAG_STACK_SERVICES=postgres,node,pool", unit)
            self.assertIn("BDAG_POOL_CONTAINER=pool", unit)
            self.assertIn("BDAG_POOL_DB_CONTAINER=postgres", unit)

        self.assertIn("bdag-status-sampler.service", root_dashboard)
        self.assertIn("BDAG_STATUS_SAMPLER_MAX_AGE_SECONDS=120", root_sampler)
        self.assertIn("BDAG_STATUS_PAYLOAD_STALE_AFTER_SECONDS=120", root_sampler)

        self.assertIn("bdag-status-sampler.service", user_dashboard)
        self.assertIn("EnvironmentFile=-/home/jeremy/blockdag-asic-pool/ops/runtime/ops.env", user_dashboard)
        self.assertIn("BDAG_STATUS_SAMPLER_MAX_AGE_SECONDS=120", user_sampler)
        self.assertIn("BDAG_STATUS_PAYLOAD_STALE_AFTER_SECONDS=120", user_sampler)

if __name__ == "__main__":
    unittest.main()
