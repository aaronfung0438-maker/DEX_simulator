"""
DexClient: thin wrapper around deployed DEX contracts.
All amounts are wei-scale (raw integers, x10^18).
"""


class DexClient:
    """Wraps SimpleDEX contract."""

    def __init__(self, chain, dex_contract, token_a_contract, token_b_contract):
        self.chain = chain
        self.w3 = chain.w3
        self.dex = dex_contract
        self.token_a = token_a_contract
        self.token_b = token_b_contract
        self.dex_address = dex_contract.address
        self.token_a_address = token_a_contract.address
        self.token_b_address = token_b_contract.address

    def get_reserves(self) -> tuple:
        return self.dex.functions.getReserves().call()

    def get_spot_price(self) -> float:
        ra, rb = self.get_reserves()
        if ra == 0:
            return 0.0
        price_scaled = self.dex.functions.getSpotPrice().call()
        return price_scaled / 1e18

    def quote_swap(self, token_in_addr: str, amount_in: int) -> int:
        if amount_in <= 0:
            return 0
        ra, rb = self.get_reserves()
        if ra == 0 or rb == 0:
            return 0
        return self.dex.functions.quoteSwap(token_in_addr, amount_in).call()

    def _approve(self, token_contract, owner: str, spender: str, amount: int):
        tx = token_contract.functions.approve(spender, amount).transact({"from": owner})
        self.w3.eth.wait_for_transaction_receipt(tx)

    def add_liquidity(self, user_addr: str, amount_a: int, amount_b: int) -> dict:
        self._approve(self.token_a, user_addr, self.dex_address, amount_a)
        self._approve(self.token_b, user_addr, self.dex_address, amount_b)
        tx_hash = self.dex.functions.addLiquidity(amount_a, amount_b).transact(
            {"from": user_addr}
        )
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        logs = self.dex.events.LiquidityAdded().process_receipt(receipt)
        new_ra, new_rb = self.get_reserves()
        return {
            "tx_hash": receipt.transactionHash.hex(),
            "gas_used": receipt.gasUsed,
            "logs_parsed": [dict(log.args) for log in logs],
            "new_reserves": (new_ra, new_rb),
        }

    def remove_liquidity(self, user_addr: str, shares: int) -> dict:
        tx_hash = self.dex.functions.removeLiquidity(shares).transact(
            {"from": user_addr}
        )
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        logs = self.dex.events.LiquidityRemoved().process_receipt(receipt)
        new_ra, new_rb = self.get_reserves()
        return {
            "tx_hash": receipt.transactionHash.hex(),
            "gas_used": receipt.gasUsed,
            "logs_parsed": [dict(log.args) for log in logs],
            "new_reserves": (new_ra, new_rb),
        }

    def swap(self, user_addr: str, token_in_addr: str, amount_in: int, amount_out_min: int) -> dict:
        if token_in_addr.lower() == self.token_a_address.lower():
            self._approve(self.token_a, user_addr, self.dex_address, amount_in)
        else:
            self._approve(self.token_b, user_addr, self.dex_address, amount_in)

        tx_hash = self.dex.functions.swap(
            token_in_addr, amount_in, amount_out_min
        ).transact({"from": user_addr})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        logs = self.dex.events.Swap().process_receipt(receipt)
        new_ra, new_rb = self.get_reserves()
        return {
            "tx_hash": receipt.transactionHash.hex(),
            "gas_used": receipt.gasUsed,
            "logs_parsed": [dict(log.args) for log in logs],
            "new_reserves": (new_ra, new_rb),
        }

    def balance_of(self, token_addr: str, user_addr: str) -> int:
        if token_addr.lower() == self.token_a_address.lower():
            return self.token_a.functions.balanceOf(user_addr).call()
        else:
            return self.token_b.functions.balanceOf(user_addr).call()

    def lp_shares_of(self, user_addr: str) -> int:
        return self.dex.functions.lpShares(user_addr).call()

    def total_lp_shares(self) -> int:
        return self.dex.functions.totalLPShares().call()


class CommitRevealDexClient:
    """Wraps CommitRevealDEX contract."""

    def __init__(self, chain, cr_dex_contract, token_a_contract, token_b_contract):
        self.chain = chain
        self.w3 = chain.w3
        self.dex = cr_dex_contract
        self.token_a = token_a_contract
        self.token_b = token_b_contract
        self.dex_address = cr_dex_contract.address
        self.token_a_address = token_a_contract.address
        self.token_b_address = token_b_contract.address

    def get_reserves(self) -> tuple:
        return self.dex.functions.getReserves().call()

    def get_spot_price(self) -> float:
        ra, rb = self.get_reserves()
        if ra == 0:
            return 0.0
        return self.dex.functions.getSpotPrice().call() / 1e18

    def quote_swap(self, token_in_addr: str, amount_in: int) -> int:
        if amount_in <= 0:
            return 0
        ra, rb = self.get_reserves()
        if ra == 0 or rb == 0:
            return 0
        return self.dex.functions.quoteSwap(token_in_addr, amount_in).call()

    def _approve(self, token_contract, owner: str, spender: str, amount: int):
        tx = token_contract.functions.approve(spender, amount).transact({"from": owner})
        self.w3.eth.wait_for_transaction_receipt(tx)

    def add_liquidity(self, user_addr: str, amount_a: int, amount_b: int) -> dict:
        self._approve(self.token_a, user_addr, self.dex_address, amount_a)
        self._approve(self.token_b, user_addr, self.dex_address, amount_b)
        tx = self.dex.functions.addLiquidity(amount_a, amount_b).transact({"from": user_addr})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)
        logs = self.dex.events.LiquidityAdded().process_receipt(receipt)
        new_ra, new_rb = self.get_reserves()
        return {
            "tx_hash": receipt.transactionHash.hex(),
            "gas_used": receipt.gasUsed,
            "logs_parsed": [dict(log.args) for log in logs],
            "new_reserves": (new_ra, new_rb),
        }

    def swap(self, user_addr: str, token_in_addr: str, amount_in: int, amount_out_min: int) -> dict:
        """Regular (non-commit-reveal) swap — used for attacks."""
        if token_in_addr.lower() == self.token_a_address.lower():
            self._approve(self.token_a, user_addr, self.dex_address, amount_in)
        else:
            self._approve(self.token_b, user_addr, self.dex_address, amount_in)

        tx = self.dex.functions.swap(token_in_addr, amount_in, amount_out_min).transact(
            {"from": user_addr}
        )
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)
        logs = self.dex.events.Swap().process_receipt(receipt)
        new_ra, new_rb = self.get_reserves()
        return {
            "tx_hash": receipt.transactionHash.hex(),
            "gas_used": receipt.gasUsed,
            "logs_parsed": [dict(log.args) for log in logs],
            "new_reserves": (new_ra, new_rb),
        }

    def commit_swap(self, user_addr: str, commit_hash: bytes) -> dict:
        tx = self.dex.functions.commitSwap(commit_hash).transact({"from": user_addr})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)
        logs = self.dex.events.SwapCommitted().process_receipt(receipt)
        return {
            "tx_hash": receipt.transactionHash.hex(),
            "gas_used": receipt.gasUsed,
            "logs_parsed": [dict(log.args) for log in logs],
        }

    def reveal_swap(
        self, user_addr: str, token_in: str, amount_in: int, amount_out_min: int, secret: bytes
    ) -> dict:
        # Approve tokens before reveal (the swap happens inside reveal)
        if token_in.lower() == self.token_a_address.lower():
            self._approve(self.token_a, user_addr, self.dex_address, amount_in)
        else:
            self._approve(self.token_b, user_addr, self.dex_address, amount_in)

        tx = self.dex.functions.revealSwap(
            token_in, amount_in, amount_out_min, secret
        ).transact({"from": user_addr})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)
        logs = self.dex.events.SwapRevealed().process_receipt(receipt)
        new_ra, new_rb = self.get_reserves()
        return {
            "tx_hash": receipt.transactionHash.hex(),
            "gas_used": receipt.gasUsed,
            "logs_parsed": [dict(log.args) for log in logs],
            "new_reserves": (new_ra, new_rb),
        }

    def compute_commit_hash(self, token_in: str, amount_in: int, amount_out_min: int, secret: bytes) -> bytes:
        return self.dex.functions.computeCommitHash(
            token_in, amount_in, amount_out_min, secret
        ).call()

    def balance_of(self, token_addr: str, user_addr: str) -> int:
        if token_addr.lower() == self.token_a_address.lower():
            return self.token_a.functions.balanceOf(user_addr).call()
        return self.token_b.functions.balanceOf(user_addr).call()

    def lp_shares_of(self, user_addr: str) -> int:
        return self.dex.functions.lpShares(user_addr).call()


class ThresholdDexClient:
    """Wraps ThresholdDEX contract."""

    def __init__(self, chain, th_dex_contract, token_a_contract, token_b_contract):
        self.chain = chain
        self.w3 = chain.w3
        self.dex = th_dex_contract
        self.token_a = token_a_contract
        self.token_b = token_b_contract
        self.dex_address = th_dex_contract.address
        self.token_a_address = token_a_contract.address
        self.token_b_address = token_b_contract.address

    def get_reserves(self) -> tuple:
        return self.dex.functions.getReserves().call()

    def get_spot_price(self) -> float:
        ra, rb = self.get_reserves()
        if ra == 0:
            return 0.0
        return self.dex.functions.getSpotPrice().call() / 1e18

    def quote_swap(self, token_in_addr: str, amount_in: int) -> int:
        if amount_in <= 0:
            return 0
        ra, rb = self.get_reserves()
        if ra == 0 or rb == 0:
            return 0
        return self.dex.functions.quoteSwap(token_in_addr, amount_in).call()

    def _approve(self, token_contract, owner: str, spender: str, amount: int):
        tx = token_contract.functions.approve(spender, amount).transact({"from": owner})
        self.w3.eth.wait_for_transaction_receipt(tx)

    def add_liquidity(self, user_addr: str, amount_a: int, amount_b: int) -> dict:
        self._approve(self.token_a, user_addr, self.dex_address, amount_a)
        self._approve(self.token_b, user_addr, self.dex_address, amount_b)
        tx = self.dex.functions.addLiquidity(amount_a, amount_b).transact({"from": user_addr})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)
        logs = self.dex.events.LiquidityAdded().process_receipt(receipt)
        new_ra, new_rb = self.get_reserves()
        return {
            "tx_hash": receipt.transactionHash.hex(),
            "gas_used": receipt.gasUsed,
            "logs_parsed": [dict(log.args) for log in logs],
            "new_reserves": (new_ra, new_rb),
        }

    def submit_encrypted_order(self, user_addr: str, commit_hash: bytes) -> dict:
        tx = self.dex.functions.submitEncryptedOrder(commit_hash).transact({"from": user_addr})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)
        logs = self.dex.events.OrderSubmitted().process_receipt(receipt)
        return {
            "tx_hash": receipt.transactionHash.hex(),
            "gas_used": receipt.gasUsed,
            "logs_parsed": [dict(log.args) for log in logs],
        }

    def close_submission_window(self, from_addr: str) -> dict:
        tx = self.dex.functions.closeSubmissionWindow().transact({"from": from_addr})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)
        return {"tx_hash": receipt.transactionHash.hex(), "gas_used": receipt.gasUsed}

    def batch_decrypt_and_execute(
        self,
        from_addr: str,
        traders: list,
        token_ins: list,
        amount_ins: list,
        amount_out_mins: list,
        secrets: list,
    ) -> dict:
        # Approve all traders' tokens before batch execution
        for i, trader in enumerate(traders):
            if token_ins[i].lower() == self.token_a_address.lower():
                self._approve(self.token_a, trader, self.dex_address, amount_ins[i])
            else:
                self._approve(self.token_b, trader, self.dex_address, amount_ins[i])

        tx = self.dex.functions.batchDecryptAndExecute(
            traders, token_ins, amount_ins, amount_out_mins, secrets
        ).transact({"from": from_addr})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx)

        batch_logs = self.dex.events.BatchDecrypted().process_receipt(receipt)
        exec_logs = self.dex.events.BatchOrderExecuted().process_receipt(receipt)
        new_ra, new_rb = self.get_reserves()

        return {
            "tx_hash": receipt.transactionHash.hex(),
            "gas_used": receipt.gasUsed,
            "batch_logs": [dict(log.args) for log in batch_logs],
            "exec_logs": [dict(log.args) for log in exec_logs],
            "new_reserves": (new_ra, new_rb),
        }

    def reset_batch(self, from_addr: str):
        tx = self.dex.functions.resetBatch().transact({"from": from_addr})
        self.w3.eth.wait_for_transaction_receipt(tx)

    def compute_commit_hash(self, token_in: str, amount_in: int, amount_out_min: int, secret: bytes) -> bytes:
        return self.dex.functions.computeCommitHash(
            token_in, amount_in, amount_out_min, secret
        ).call()

    def balance_of(self, token_addr: str, user_addr: str) -> int:
        if token_addr.lower() == self.token_a_address.lower():
            return self.token_a.functions.balanceOf(user_addr).call()
        return self.token_b.functions.balanceOf(user_addr).call()

    def get_pending_count(self) -> int:
        return self.dex.functions.getPendingTraderCount().call()

    def get_batch_phase(self) -> int:
        return self.dex.functions.currentPhase().call()
