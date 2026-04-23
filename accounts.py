"""
Simulated account mapping.
Index 0 = deployer/system. Indices 1-5 = named users.
Eve (index 5) is the attacker in scenarios 2-4.
"""

ACCOUNTS = {
    "Alice": 1,
    "Bob": 2,
    "Carol": 3,
    "Dave": 4,
    "Eve": 5,  # Attacker
}


def address_of(chain, name: str) -> str:
    """Return the address for a named account."""
    return chain.accounts[ACCOUNTS[name]]


def get_account_labels(chain) -> dict:
    """Returns {name: {address, private_key, index}} for all named accounts."""
    result = {}
    for name, idx in ACCOUNTS.items():
        addr = chain.accounts[idx]
        pk = chain.get_private_key(idx)
        result[name] = {
            "address": addr,
            "private_key": pk,
            "index": idx,
        }
    return result
