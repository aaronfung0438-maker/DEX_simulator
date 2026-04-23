# DEX Simulator

**IEDA 4000J — Blockchain and Web3 | HKUST**

An interactive educational simulator that teaches DEX mechanics, MEV attacks, and progressive defense mechanisms through guided, step-by-step scenarios backed by real Solidity smart contracts on an in-memory EVM.

## What This Teaches

This simulator walks students through **5 guided scenarios** that build on each other, plus a free-play mode:

| Mode | Topic | What You Learn |
|------|-------|---------------|
| 1️⃣ Simple DEX | AMM basics | Pool creation, constant-product formula, price impact, LP fees |
| 2️⃣ Sandwich Attack | MEV exploitation | How front-running + back-running extracts value from victims |
| 3️⃣ Commit-Reveal | Defense layer 1 | Hiding trade details to prevent sandwich attacks |
| 4️⃣ Last Revealer | Commit-Reveal flaw | Information asymmetry in sequential reveal |
| 5️⃣ Threshold Encryption | Defense layer 2 | Batch execution eliminates ordering advantages |
| 6️⃣ Free Mode | Open sandbox | Full DEX operations without guided steps |

Each scenario is semi-interactive: parameters are pre-filled but adjustable, with "Next Step" buttons to advance. Every step includes expandable math showing the full Uniswap V2 formula with actual numbers substituted in.

## Setup

```bash
# 1. Navigate to project directory
cd dex-prototype

# 2. Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate        # Linux/macOS
# venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set environment variable (Windows — required for eth-hash)
# PowerShell:
$env:ETH_HASH_BACKEND = "pycryptodome"
# CMD:
set ETH_HASH_BACKEND=pycryptodome
# Linux/macOS:
export ETH_HASH_BACKEND=pycryptodome

# 5. Run
streamlit run frontend/app.py
```

First launch takes ~5 seconds (compiling 5 Solidity contracts + deploying to in-memory EVM).

## Login

The simulator uses **private key login** for educational purposes. On the login page, you'll see pre-funded test accounts (Alice, Bob, Carol, Dave, Eve) with their private keys displayed. Copy any key and paste it to log in.

**These are test-only keys on a local in-memory EVM. They have zero real-world value.**

## Project Structure

```
dex-prototype/
├── contracts/
│   ├── TokenA.sol              # ERC-20 Token A
│   ├── TokenB.sol              # ERC-20 Token B
│   ├── SimpleDEX.sol           # Basic constant-product AMM
│   ├── CommitRevealDEX.sol     # AMM + commit-reveal swap mechanism
│   └── ThresholdDEX.sol        # AMM + batch encrypted execution
├── backend/
│   ├── compile.py              # py-solc-x compilation
│   ├── chain.py                # eth-tester EVM session
│   ├── accounts.py             # Account name ↔ address mapping
│   └── dex_client.py           # Python wrappers for all 3 DEX contracts
├── frontend/
│   └── app.py                  # Streamlit UI (all 6 modes)
├── requirements.txt
└── README.md
```

## Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Frontend | Streamlit | Browser UI with guided scenarios |
| Backend | Python + web3.py | Contract interaction |
| Smart Contracts | Solidity ^0.8.20 | AMM logic + defense mechanisms |
| EVM | eth-tester (PyEVM) | In-memory deterministic blockchain |
| Compiler | py-solc-x | Solidity → ABI + bytecode |

## Key Math

**Constant Product**: `x · y = k`

**Swap Output (0.3% fee)**: `Δy = (y · Δx · 997) / (x · 1000 + Δx · 997)`

**Price Impact**: `(execution_price - spot_price) / spot_price`

All math is computed on-chain in Solidity using integer arithmetic, identical to Uniswap V2.
