# DEX Simulator

**IEDA 4000J — Blockchain and Web3 | HKUST**

An interactive educational simulator that teaches DEX mechanics, MEV attacks, and progressive defense mechanisms through guided, step-by-step scenarios backed by real Solidity smart contracts on an in-memory EVM.

## What This Teaches

This simulator walks students through **5 guided scenarios** that build on each other, plus a free-play mode:

| Mode | Topic | What You Learn |
|------|-------|---------------|
| 1. Simple DEX | AMM basics | Pool creation, constant-product formula, price impact, LP fees |
| 2. Sandwich Attack | MEV exploitation | How front-running + back-running extracts value from victims |
| 3. Commit-Reveal | Defense layer 1 | Hiding trade details to prevent sandwich attacks |
| 4. Last Revealer | Commit-Reveal flaw | Information asymmetry in sequential reveal |
| 5. Threshold Encryption | Defense layer 2 | Batch execution eliminates ordering advantages |
| 6. Free Mode | Open sandbox | Full DEX operations without guided steps |

Each scenario is semi-interactive: parameters are pre-filled but adjustable, with "Next Step" buttons to advance. Every step includes expandable math showing the full Uniswap V2 formula with actual numbers substituted in.

## Setup

```powershell
# 1. Navigate to project directory
cd DEX_simulator

# 2. Create virtual environment (recommended)
python -m venv venv
venv\Scripts\activate          # Windows (PowerShell)
# source venv/bin/activate     # Linux/macOS

# 3. Install dependencies
pip install "setuptools<81"
pip install --pre -r requirements.txt

# 4. Set environment variable (required for eth-hash on Windows)
# PowerShell:
$env:ETH_HASH_BACKEND = "pycryptodome"
# CMD:
# set ETH_HASH_BACKEND=pycryptodome
# Linux/macOS:
# export ETH_HASH_BACKEND=pycryptodome

# 5. Run
streamlit run app.py
```

First launch takes ~5 seconds (compiling 5 Solidity contracts + deploying to in-memory EVM).

## Usage

1. Open the app in your browser (Streamlit auto-opens at `http://localhost:8501`).
2. From the overview page, pick a scenario (Modes 1–6).
3. Modes 2–5 are guided tutorials and **do not require login**; they auto-seed the pool with 10,000 TKA + 10,000 TKB if empty.
4. Modes 1 and 6 require you to select a test account (Alice / Bob / Carol / Dave / Eve).

**All accounts are test-only on a local in-memory EVM and have zero real-world value.**

## Project Structure

```
DEX_simulator/
├── TokenA.sol              # ERC-20 Token A
├── TokenB.sol              # ERC-20 Token B
├── SimpleDEX.sol           # Basic constant-product AMM
├── CommitRevealDEX.sol     # AMM + commit-reveal swap mechanism
├── ThresholdDEX.sol        # AMM + batch encrypted execution
├── app.py                  # Streamlit UI (all 6 modes)
├── chain.py                # eth-tester EVM session
├── compile.py              # py-solc-x compilation helper
├── accounts.py             # Account name ↔ address mapping
├── dex_client.py           # Python wrappers for all 3 DEX contracts
├── requirements.txt
├── .gitignore
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
