"""Configuration management for cointools."""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".cointools"
CONFIG_FILE = CONFIG_DIR / "config.json"
CACHE_DB = CONFIG_DIR / "cache.db"

DEFAULT_SOLANA_RPC = "https://api.mainnet-beta.solana.com"

SUPPORTED_CHAINS = ["solana", "base", "eth", "optimism", "arbitrum", "polygon", "bsc"]

PERIOD_SECONDS = {
    "1h": 3600,
    "24h": 86400,
    "7d": 604800,
    "30d": 2592000,
}


def _ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    _ensure_config_dir()
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def save_config(cfg: dict) -> None:
    _ensure_config_dir()
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def get_rpc_url(chain: str = "solana") -> str:
    cfg = load_config()
    chain_key = f"rpc_url_{chain}"
    if chain_key in cfg:
        return cfg[chain_key]
    # Legacy key fallback for solana
    if chain == "solana" and "rpc_url" in cfg:
        return cfg["rpc_url"]
    return DEFAULT_SOLANA_RPC


def set_rpc_url(url: str, chain: str = "solana") -> None:
    cfg = load_config()
    cfg[f"rpc_url_{chain}"] = url
    save_config(cfg)


def detect_chain(address: str) -> str:
    """Auto-detect chain from address format.

    - 0x... (42 chars) → EVM (defaults to 'base')
    - Base58 string (32-44 chars) → Solana
    """
    if address.startswith("0x") and len(address) == 42:
        return "base"
    return "solana"
