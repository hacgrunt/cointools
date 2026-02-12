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

SCOUT_PERIOD_SECONDS = {
    "1h": 3600,
    "6h": 21600,
    "12h": 43200,
    "24h": 86400,
    "3d": 259200,
    "7d": 604800,
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


def get_helius_api_key() -> str | None:
    """Return the stored Helius API key, or try to extract from the RPC URL."""
    cfg = load_config()
    if cfg.get("helius_api_key"):
        return cfg["helius_api_key"]
    # Try to extract from Solana RPC URL (helius URLs embed the key)
    rpc = get_rpc_url("solana")
    if "helius" in rpc and "api-key=" in rpc:
        return rpc.split("api-key=")[-1].split("&")[0]
    if "helius" in rpc and "?" in rpc:
        return rpc.split("?")[-1].split("&")[0]
    return None


def set_helius_api_key(key: str) -> None:
    cfg = load_config()
    cfg["helius_api_key"] = key
    save_config(cfg)


def detect_chain(address: str) -> str:
    """Auto-detect chain from address format.

    - 0x... (42 chars) → EVM (defaults to 'base')
    - Base58 string (32-44 chars) → Solana
    """
    if address.startswith("0x") and len(address) == 42:
        return "base"
    return "solana"
