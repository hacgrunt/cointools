"""Tests for scout.scanner module — swap parsing logic."""

from cointools.scout.scanner import parse_swap_transaction


def _swap_tx(
    signature="sig123",
    timestamp=1700000000,
    source="JUPITER",
    native_input=None,
    native_output=None,
    token_inputs=None,
    token_outputs=None,
):
    """Build a minimal Helius enhanced transaction dict."""
    swap = {}
    if native_input is not None:
        swap["nativeInput"] = {"account": "wallet", "amount": str(native_input)}
    if native_output is not None:
        swap["nativeOutput"] = {"account": "wallet", "amount": str(native_output)}
    swap["tokenInputs"] = token_inputs or []
    swap["tokenOutputs"] = token_outputs or []

    return {
        "signature": signature,
        "timestamp": timestamp,
        "source": source,
        "type": "SWAP",
        "events": {"swap": swap},
    }


def _token(mint, amount, decimals=6):
    """Build a token entry for swap events."""
    return {
        "mint": mint,
        "rawTokenAmount": {
            "tokenAmount": str(int(amount * (10**decimals))),
            "decimals": decimals,
        },
    }


RANDOM_TOKEN = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WSOL = "So11111111111111111111111111111111111111112"
WALLET = "TestWallet123"


class TestParseSwapTransaction:
    def test_sol_to_token_buy(self):
        """Spending SOL, receiving a token = BUY."""
        tx = _swap_tx(
            native_input=500_000_000,  # 0.5 SOL in lamports
            token_outputs=[_token(RANDOM_TOKEN, 1000.0)],
        )
        trades = parse_swap_transaction(tx, WALLET)
        assert len(trades) == 1
        assert trades[0]["trade_type"] == "BUY"
        assert trades[0]["token_mint"] == RANDOM_TOKEN
        assert trades[0]["token_amount"] == 1000.0
        assert abs(trades[0]["sol_amount"] - 0.5) < 0.001

    def test_token_to_sol_sell(self):
        """Sending a token, receiving SOL = SELL."""
        tx = _swap_tx(
            native_output=2_000_000_000,  # 2 SOL
            token_inputs=[_token(RANDOM_TOKEN, 5000.0)],
        )
        trades = parse_swap_transaction(tx, WALLET)
        assert len(trades) == 1
        assert trades[0]["trade_type"] == "SELL"
        assert trades[0]["token_mint"] == RANDOM_TOKEN
        assert abs(trades[0]["sol_amount"] - 2.0) < 0.001

    def test_usdc_to_token_buy(self):
        """Spending USDC, receiving a token = BUY (stablecoin proxied)."""
        tx = _swap_tx(
            token_inputs=[_token(USDC, 100.0)],
            token_outputs=[_token(RANDOM_TOKEN, 5000.0)],
        )
        trades = parse_swap_transaction(tx, WALLET)
        assert len(trades) == 1
        assert trades[0]["trade_type"] == "BUY"
        assert trades[0]["token_mint"] == RANDOM_TOKEN

    def test_token_to_usdc_sell(self):
        """Sending a token, receiving USDC = SELL."""
        tx = _swap_tx(
            token_inputs=[_token(RANDOM_TOKEN, 5000.0)],
            token_outputs=[_token(USDC, 100.0)],
        )
        trades = parse_swap_transaction(tx, WALLET)
        assert len(trades) == 1
        assert trades[0]["trade_type"] == "SELL"

    def test_wsol_skipped_as_base(self):
        """Wrapped SOL output should be skipped as base token."""
        tx = _swap_tx(
            token_inputs=[_token(RANDOM_TOKEN, 1000.0)],
            token_outputs=[_token(WSOL, 0.5, decimals=9)],
            native_output=500_000_000,
        )
        trades = parse_swap_transaction(tx, WALLET)
        assert len(trades) == 1
        assert trades[0]["trade_type"] == "SELL"

    def test_dust_filtered(self):
        """Trades below MIN_TRADE_SOL should be filtered out."""
        tx = _swap_tx(
            native_input=1_000,  # 0.000001 SOL — dust
            token_outputs=[_token(RANDOM_TOKEN, 1.0)],
        )
        trades = parse_swap_transaction(tx, WALLET)
        assert len(trades) == 0

    def test_token_to_token_swap(self):
        """Token A → Token B = SELL A + BUY B."""
        token_a = "TokenA111111111111111111111111111111111111111"
        token_b = "TokenB222222222222222222222222222222222222222"
        tx = _swap_tx(
            native_input=1_000_000_000,  # 1 SOL (intermediate)
            token_inputs=[_token(token_a, 500.0)],
            token_outputs=[_token(token_b, 300.0)],
        )
        trades = parse_swap_transaction(tx, WALLET)
        assert len(trades) == 2
        types = {t["trade_type"] for t in trades}
        assert types == {"BUY", "SELL"}
        mints = {t["token_mint"] for t in trades}
        assert mints == {token_a, token_b}

    def test_no_swap_event(self):
        """Transaction without swap event returns empty."""
        tx = {"signature": "x", "timestamp": 1000, "events": {}}
        assert parse_swap_transaction(tx, WALLET) == []

    def test_metadata_preserved(self):
        """Wallet address, signature, timestamp, source should be preserved."""
        tx = _swap_tx(
            signature="SIG_ABC",
            timestamp=1700000000,
            source="RAYDIUM",
            native_input=1_000_000_000,
            token_outputs=[_token(RANDOM_TOKEN, 100.0)],
        )
        trades = parse_swap_transaction(tx, "MY_WALLET")
        assert trades[0]["wallet_address"] == "MY_WALLET"
        assert trades[0]["signature"] == "SIG_ABC"
        assert trades[0]["timestamp"] == 1700000000
        assert trades[0]["source"] == "RAYDIUM"
