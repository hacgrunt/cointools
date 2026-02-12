"""Tests for scout.filters module."""

from cointools.scout.filters import (
    BASE_TOKENS,
    EXCHANGE_WALLETS,
    KNOWN_PROGRAMS,
    STABLECOINS,
    WRAPPED_SOL,
    is_base_token,
    is_dust_trade,
    is_exchange_wallet,
    is_known_program,
)


class TestIsBaseToken:
    def test_usdc(self):
        assert is_base_token("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")

    def test_usdt(self):
        assert is_base_token("Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB")

    def test_wrapped_sol(self):
        assert is_base_token(WRAPPED_SOL)

    def test_random_token_not_base(self):
        assert not is_base_token("7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr")


class TestIsDustTrade:
    def test_below_threshold(self):
        assert is_dust_trade(0.005)

    def test_at_threshold(self):
        # 0.01 is NOT dust (it's >= MIN_TRADE_SOL)
        assert not is_dust_trade(0.01)

    def test_above_threshold(self):
        assert not is_dust_trade(1.5)

    def test_zero(self):
        assert is_dust_trade(0.0)

    def test_negative_small(self):
        assert is_dust_trade(-0.005)


class TestIsKnownProgram:
    def test_system_program(self):
        assert is_known_program("11111111111111111111111111111111")

    def test_token_program(self):
        assert is_known_program("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")

    def test_jupiter(self):
        assert is_known_program("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4")

    def test_random_not_program(self):
        assert not is_known_program("ABCdef1234567890abcdef1234567890ab")


class TestIsExchangeWallet:
    def test_binance(self):
        assert is_exchange_wallet("5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9")

    def test_random_not_exchange(self):
        assert not is_exchange_wallet("RandomWalletAddress12345")


class TestConstants:
    def test_stablecoins_subset_of_base(self):
        assert STABLECOINS.issubset(BASE_TOKENS)

    def test_wrapped_sol_in_base(self):
        assert WRAPPED_SOL in BASE_TOKENS

    def test_known_programs_not_empty(self):
        assert len(KNOWN_PROGRAMS) > 10

    def test_exchange_wallets_not_empty(self):
        assert len(EXCHANGE_WALLETS) >= 5
