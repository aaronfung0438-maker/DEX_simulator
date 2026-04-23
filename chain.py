"""
ChainSession: wraps eth-tester + web3.py.
Compiles and deploys all contracts on init.
Distributes initial token balances to all user accounts.
"""
import os
from eth_tester import EthereumTester, PyEVMBackend
from web3 import Web3
from web3.providers.eth_tester import EthereumTesterProvider
from eth_account import Account

from compile import compile_contract
from accounts import ACCOUNTS

CONTRACTS_DIR = os.path.dirname(os.path.abspath(__file__))

INITIAL_SUPPLY = 1_000_000 * 10**18
USER_MINT_AMOUNT = 100_000 * 10**18


class ChainSession:
    def __init__(self):
        self.tester = EthereumTester(PyEVMBackend())
        self.w3 = Web3(EthereumTesterProvider(self.tester))
        self.accounts = self.tester.get_accounts()

        # Extract private keys
        self._private_keys = {}
        self._extract_private_keys()

        # Compile all contracts
        self.token_a_abi, self.token_a_bin = compile_contract(
            os.path.join(CONTRACTS_DIR, "TokenA.sol")
        )
        self.token_b_abi, self.token_b_bin = compile_contract(
            os.path.join(CONTRACTS_DIR, "TokenB.sol")
        )
        self.dex_abi, self.dex_bin = compile_contract(
            os.path.join(CONTRACTS_DIR, "SimpleDEX.sol")
        )
        self.cr_dex_abi, self.cr_dex_bin = compile_contract(
            os.path.join(CONTRACTS_DIR, "CommitRevealDEX.sol")
        )
        self.th_dex_abi, self.th_dex_bin = compile_contract(
            os.path.join(CONTRACTS_DIR, "ThresholdDEX.sol")
        )

        deployer = self.accounts[0]

        # Deploy tokens
        self.token_a_contract = self._deploy(
            self.token_a_abi, self.token_a_bin, deployer, [INITIAL_SUPPLY]
        )
        self.token_b_contract = self._deploy(
            self.token_b_abi, self.token_b_bin, deployer, [INITIAL_SUPPLY]
        )

        token_a_addr = self.token_a_contract.address
        token_b_addr = self.token_b_contract.address

        # Deploy all three DEX variants
        self.dex_contract = self._deploy(
            self.dex_abi, self.dex_bin, deployer, [token_a_addr, token_b_addr]
        )
        self.cr_dex_contract = self._deploy(
            self.cr_dex_abi, self.cr_dex_bin, deployer, [token_a_addr, token_b_addr]
        )
        self.th_dex_contract = self._deploy(
            self.th_dex_abi, self.th_dex_bin, deployer, [token_a_addr, token_b_addr]
        )

        # Mint tokens to every named user
        for name, idx in ACCOUNTS.items():
            user_addr = self.accounts[idx]
            tx = self.token_a_contract.functions.mint(
                user_addr, USER_MINT_AMOUNT
            ).transact({"from": deployer})
            self.w3.eth.wait_for_transaction_receipt(tx)
            tx = self.token_b_contract.functions.mint(
                user_addr, USER_MINT_AMOUNT
            ).transact({"from": deployer})
            self.w3.eth.wait_for_transaction_receipt(tx)

    def _extract_private_keys(self):
        """Extract private keys from eth-tester backend."""
        backend = self.tester.backend
        try:
            for i, key in enumerate(backend.account_keys):
                addr = self.accounts[i].lower()
                if hasattr(key, "to_hex"):
                    self._private_keys[addr] = key.to_hex()
                else:
                    self._private_keys[addr] = "0x" + key.hex()
        except AttributeError:
            try:
                for i in range(len(self.accounts)):
                    addr = self.accounts[i].lower()
                    key = self.tester.backend._key_lookup.get(
                        bytes.fromhex(addr[2:])
                    )
                    if key:
                        self._private_keys[addr] = "0x" + key.hex()
            except (AttributeError, KeyError):
                print("Warning: Could not extract private keys from eth-tester backend.")

    def get_private_key(self, index: int) -> str:
        addr = self.accounts[index].lower()
        return self._private_keys.get(addr, "unknown")

    def address_from_private_key(self, private_key: str) -> str:
        """Derive address from private key, return matched account or None."""
        try:
            acct = Account.from_key(private_key)
            derived = acct.address.lower()
            for addr in self.accounts:
                if addr.lower() == derived:
                    return addr
            return None
        except Exception:
            return None

    def get_account_name(self, address: str) -> str:
        addr_lower = address.lower()
        for name, idx in ACCOUNTS.items():
            if self.accounts[idx].lower() == addr_lower:
                return name
        if self.accounts[0].lower() == addr_lower:
            return "Deployer"
        return "Unknown"

    def mine_block(self):
        """Force mine a new block (needed for commit-reveal timing)."""
        self.tester.mine_block()

    def take_snapshot(self):
        """Return snapshot id for revert_to_snapshot (eth-tester)."""
        return self.tester.take_snapshot()

    def revert_to_snapshot(self, snapshot_id):
        """Revert chain state; invalidates snapshots taken after this one."""
        self.tester.revert_to_snapshot(snapshot_id)

    def _deploy(self, abi, bytecode, deployer, constructor_args=None):
        if constructor_args is None:
            constructor_args = []
        contract = self.w3.eth.contract(abi=abi, bytecode=bytecode)
        tx_hash = contract.constructor(*constructor_args).transact({"from": deployer})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return self.w3.eth.contract(address=receipt.contractAddress, abi=abi)
