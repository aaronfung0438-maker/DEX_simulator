"""
DEX Simulator — Streamlit Frontend
IEDA 4000J — Blockchain and Web3 | HKUST

6 Modes:
  1. Simple DEX        — Learn pool creation, liquidity, swaps
  2. Sandwich Attack   — See how MEV attackers exploit mempool visibility
  3. Commit-Reveal     — Defense against sandwich attacks
  4. Last Revealer     — Vulnerability in commit-reveal
  5. Threshold Encrypt — Batch execution defense
  6. Free Mode         — Unrestricted trading
"""
import sys, os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
from chain import ChainSession
from dex_client import DexClient, CommitRevealDexClient, ThresholdDexClient
from accounts import ACCOUNTS, address_of, get_account_labels

st.set_page_config(page_title="DEX Simulator", layout="wide")

# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------
SCALE = 10**18


def to_h(wei): return wei / SCALE
def to_w(human): return int(human * SCALE)
def short(addr): return f"{addr[:6]}...{addr[-4:]}"


def show_math(label, formula, values, result):
    """Expandable math block (avoid st.latex — causes React removeChild errors on Windows)."""
    with st.expander(f"📐 Math: {label}"):
        st.code(formula, language="text")
        st.code(values, language="text")
        st.success(f"Result: {result}")


def show_tx_receipt(result: dict, contract_name: str, fn_name: str, event_key: str = "logs_parsed"):
    """Show EVM transaction receipt — proves the Solidity function actually ran on-chain."""
    tx_hash = result.get("tx_hash", "")
    block_num = result.get("block_number", "?")
    gas_used = result.get("gas_used", "?")
    logs = result.get(event_key, [])

    with st.expander("🔗 EVM Transaction Receipt  ← Solidity actually ran this"):
        col1, col2, col3 = st.columns(3)
        col1.metric("Block #", block_num)
        col2.metric("Gas Used", f"{gas_used:,}" if isinstance(gas_used, int) else gas_used)
        col3.metric("Contract", contract_name)

        st.caption(f"Function called: `{contract_name}.{fn_name}(...)`")
        st.code(f"tx hash: {tx_hash}", language="text")

        if logs:
            st.markdown("**Events emitted by Solidity:**")
            for log in logs:
                formatted = {
                    k: (f"{v / 1e18:,.4f} tokens" if isinstance(v, int) and v > 10**15 else
                        (f"0x{v.hex()}" if isinstance(v, (bytes, bytearray)) else v))
                    for k, v in log.items()
                }
                st.json(formatted)


def show_pool_state(client, label="Current Pool State"):
    """Display pool reserves, k, spot price."""
    ra, rb = client.get_reserves()
    ra_h, rb_h = to_h(ra), to_h(rb)
    k_h = ra_h * rb_h
    st.markdown(f"**{label}**")
    c1, c2, c3 = st.columns(3)
    c1.metric("Reserve A (TKA)", f"{ra_h:,.2f}")
    c2.metric("Reserve B (TKB)", f"{rb_h:,.2f}")
    c3.metric("k = x · y", f"{k_h:,.0f}")
    if ra > 0:
        spot = client.get_spot_price()
        st.metric("Spot Price (TKB per TKA)", f"{spot:,.6f}")


def add_tx(tag, user, details, reserves, extra=None):
    """Append to transaction history."""
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "tag": tag,
        "user": user,
        "details": details,
        "reserves": reserves,
    }
    if extra:
        entry.update(extra)
    st.session_state.tx_history.insert(0, entry)


def compute_swap_output(reserve_in, reserve_out, amount_in):
    """Python-side swap formula mirroring Solidity (for math display)."""
    numerator = reserve_out * amount_in * 997
    denominator = reserve_in * 1000 + amount_in * 997
    return numerator // denominator


def ensure_default_pool(dex, chain):
    """If SimpleDEX pool is empty, Alice seeds 10,000 + 10,000 (modes 2–5 skip Mode 1)."""
    ra, rb = dex.get_reserves()
    if ra == 0 and rb == 0:
        alice = address_of(chain, "Alice")
        dex.add_liquidity(alice, to_w(10000), to_w(10000))


def ensure_cr_pool_synced(dex, cr_dex, chain):
    """Mirror SimpleDEX reserves into CommitReveal pool if the latter is empty."""
    ra, rb = dex.get_reserves()
    cra, crb = cr_dex.get_reserves()
    if ra > 0 and rb > 0 and cra == 0 and crb == 0:
        cr_dex.add_liquidity(chain.accounts[0], ra, rb)


def init_guided_stack(chain, stack_key: str):
    if stack_key not in st.session_state or not st.session_state[stack_key]:
        st.session_state[stack_key] = [chain.take_snapshot()]


def guided_prev_step(chain, step_key: str, stack_key: str):
    """Undo last guided step via eth-tester snapshot (step >= 2 reverts chain)."""
    step = st.session_state[step_key]
    stack = st.session_state[stack_key]
    if step <= 0:
        return
    if step == 1:
        st.session_state[step_key] = 0
        if step_key == "s1_step":
            st.session_state.pop("s1_seed", None)
        st.rerun()
        return
    if len(stack) >= 2:
        target = stack[-2]
        chain.revert_to_snapshot(target)
        stack.pop()
    st.session_state[step_key] = step - 1
    if step_key == "s1_step" and st.session_state[step_key] < 2:
        st.session_state.pop("s1_seed", None)
    st.rerun()


def guided_after_tx(chain, stack_key: str):
    st.session_state[stack_key].append(chain.take_snapshot())


def render_guided_nav(chain, step_key: str, stack_key: str, step: int, reset_fn):
    c1, c2 = st.columns(2)
    with c1:
        if st.button("⬅️ Previous step", key=f"{step_key}_prev"):
            guided_prev_step(chain, step_key, stack_key)
    with c2:
        if st.button("🔄 Reset scenario", key=f"{step_key}_reset"):
            reset_fn()


# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------
if "chain" not in st.session_state:
    with st.spinner("Booting local EVM, compiling & deploying 5 contracts..."):
        chain = ChainSession()
        dex = DexClient(chain, chain.dex_contract, chain.token_a_contract, chain.token_b_contract)
        cr_dex = CommitRevealDexClient(chain, chain.cr_dex_contract, chain.token_a_contract, chain.token_b_contract)
        th_dex = ThresholdDexClient(chain, chain.th_dex_contract, chain.token_a_contract, chain.token_b_contract)
    st.session_state.chain = chain
    st.session_state.dex = dex
    st.session_state.cr_dex = cr_dex
    st.session_state.th_dex = th_dex
    st.session_state.current_user = None
    st.session_state.current_user_name = None
    st.session_state.tx_history = []
    # Step trackers for each scenario
    st.session_state.s1_step = 0
    st.session_state.s2_step = 0
    st.session_state.s3_step = 0
    st.session_state.s4_step = 0
    st.session_state.s5_step = 0
    # Snapshot data for scenarios
    st.session_state.s2_data = {}
    st.session_state.s3_data = {}
    st.session_state.s4_data = {}
    st.session_state.s5_data = {}
    for k in ("s1_stack", "s2_stack", "s3_stack", "s4_stack", "s5_stack"):
        st.session_state[k] = []

chain = st.session_state.chain
dex = st.session_state.dex
cr_dex = st.session_state.cr_dex
th_dex = st.session_state.th_dex


# ---------------------------------------------------------------------------
# Character select (Mode 1 & 6 only)
# ---------------------------------------------------------------------------
def page_character_select():
    mode = st.session_state.get("current_mode", "1")
    st.title("🏦 DEX Simulator")
    st.subheader("IEDA 4000J — Blockchain and Web3 | HKUST")
    if mode == "1":
        st.markdown("**Mode 1 — Simple DEX**: pick which test account you want to act as (the guided flow still uses Alice / Bob / Carol for demonstration).")
    else:
        st.markdown("**Mode 6 — Free Mode**: pick the account you want to operate.")
    names = list(ACCOUNTS.keys())
    choice = st.selectbox("Account", names, key="char_select_box")
    if st.button("Enter", type="primary"):
        addr = address_of(chain, choice)
        st.session_state.current_user = addr
        st.session_state.current_user_name = choice
        st.rerun()
    st.divider()
    st.caption("Test accounts (local in-memory chain, no real assets)")
    for name, info in get_account_labels(chain).items():
        role = " — attacker script" if name == "Eve" else ""
        st.text(f"{name}{role}: {short(info['address'])}")


# ---------------------------------------------------------------------------
# OVERVIEW PAGE — mode selection
# ---------------------------------------------------------------------------
def page_overview():
    st.title("🏦 DEX Simulator — Choose a Scenario")
    st.markdown("Modes 2–5 are guided tutorials and do not require login. Modes 1 and 6 need a test account. If no pool exists yet, modes 2–5 auto-seed 10,000 TKA + 10,000 TKB from Alice.")

    modes = [
        ("1", "1️⃣ Simple DEX", "Learn how a constant-product AMM works: create a pool, add liquidity, swap tokens, and see the math behind every trade."),
        ("2", "2️⃣ Sandwich Attack", "See how an attacker (Eve) exploits mempool visibility to front-run and back-run a victim's trade for profit."),
        ("3", "3️⃣ Commit-Reveal Defense", "Learn how hiding trade details with a commit-reveal scheme prevents sandwich attacks — and watch Eve's blind guess fail."),
        ("4", "4️⃣ Last Revealer Attack", "Discover the vulnerability in commit-reveal: the last person to reveal has an information advantage."),
        ("5", "5️⃣ Threshold Encryption", "See how batch execution with encrypted orders eliminates the last-revealer problem."),
        ("6", "6️⃣ Free Mode", "No guides — trade freely with full control over all DEX operations."),
    ]

    for mid, mode_title, desc in modes:
        with st.container():
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f"### {mode_title}")
                st.caption(desc)
            with col2:
                st.markdown("")
                if st.button("Start", key=f"ov_start_{mid}"):
                    st.session_state.current_mode = mid
                    st.session_state.current_user = None
                    st.session_state.current_user_name = None
                    if mid == "1":
                        st.session_state.s1_stack = []
                        st.session_state.s1_step = 0
                        st.session_state.pop("s1_seed", None)
                    elif mid == "2":
                        st.session_state.s2_stack = []
                        st.session_state.s2_step = 0
                        st.session_state.s2_data = {}
                    elif mid == "3":
                        st.session_state.s3_stack = []
                        st.session_state.s3_step = 0
                        st.session_state.s3_data = {}
                    elif mid == "4":
                        st.session_state.s4_stack = []
                        st.session_state.s4_step = 0
                        st.session_state.s4_data = {}
                    elif mid == "5":
                        st.session_state.s5_stack = []
                        st.session_state.s5_step = 0
                        st.session_state.s5_data = {}
                        th_dex.reset_batch(chain.accounts[0])
                    st.rerun()


# ---------------------------------------------------------------------------
# MODE 1: Simple DEX
# ---------------------------------------------------------------------------
def mode_simple_dex():
    st.title("1️⃣ Simple DEX — Learn the Basics")
    step = st.session_state.s1_step
    init_guided_stack(chain, "s1_stack")

    def reset_mode_1():
        stack = st.session_state.get("s1_stack", [])
        if len(stack) >= 1:
            chain.revert_to_snapshot(stack[0])
        st.session_state.s1_stack = [chain.take_snapshot()]
        st.session_state.s1_step = 0
        st.session_state.pop("s1_seed", None)
        st.rerun()

    col_l, col_r = st.columns([3, 1])
    with col_r:
        st.caption(f"Step {step}/4")
        render_guided_nav(chain, "s1_step", "s1_stack", step, reset_mode_1)

    with col_l:
        if step == 0:
            st.markdown("### Welcome to the DEX Simulator!")
            st.markdown(
                "In this scenario, you will:\n"
                "1. **Seed a liquidity pool** with TokenA and TokenB\n"
                "2. **Execute a swap** and see the constant-product formula in action\n"
                "3. **Execute a reverse swap** and observe price elasticity\n"
                "4. **Remove liquidity** and see how fees accumulate\n\n"
                "Click **Next Step** to begin."
            )
            if st.button("Next Step ➡️", key="s1_next_0"):
                st.session_state.s1_step = 1
                st.rerun()

        elif step == 1:
            st.markdown("### Step 1: Seed the Liquidity Pool")
            st.markdown("**Alice** deposits TokenA and TokenB to create the pool. This sets the initial price ratio.")

            amt_a = st.number_input("TokenA amount", value=10000.0, min_value=1.0, step=1000.0, key="s1_amtA")
            amt_b = st.number_input("TokenB amount", value=10000.0, min_value=1.0, step=1000.0, key="s1_amtB")

            st.info(f"Initial price: 1 TKA = {amt_b/amt_a:.4f} TKB")

            if st.button("Alice: Seed Pool ➡️", type="primary", key="s1_exec_1"):
                alice = address_of(chain, "Alice")
                ra_pre, rb_pre = dex.get_reserves()

                if ra_pre > 0 and rb_pre > 0:
                    # Pool already seeded by another mode — skip add_liquidity to avoid ratio mismatch.
                    ra_h, rb_h = to_h(ra_pre), to_h(rb_pre)
                    st.info(
                        f"Pool already has reserves ({ra_h:,.2f} TKA / {rb_h:,.2f} TKB) from a previous scenario. "
                        "Skipping deposit and using existing pool."
                    )
                    show_math(
                        "LP Shares (pool already seeded)",
                        "shares = sqrt(x · y)",
                        f"Using existing pool: {ra_h:,.2f} TKA × {rb_h:,.2f} TKB",
                        f"Pool live — k = {ra_h * rb_h:,.0f}"
                    )
                    st.session_state.s1_seed = {"a": ra_h, "b": rb_h}
                    guided_after_tx(chain, "s1_stack")
                    st.session_state.s1_step = 2
                    st.rerun()
                else:
                    result = dex.add_liquidity(alice, to_w(amt_a), to_w(amt_b))
                    shares = result["logs_parsed"][0]["sharesMinted"] if result["logs_parsed"] else 0

                    show_math(
                        "LP Shares (first deposit)",
                        "shares = sqrt(x · y)",
                        f"shares = sqrt({amt_a:,.0f} × {amt_b:,.0f}) = {to_h(shares):,.4f}",
                        f"{to_h(shares):,.4f} LP shares minted"
                    )
                    show_tx_receipt(result, "SimpleDEX", "addLiquidity")

                    add_tx("⚪ Seed Pool", "Alice", f"{amt_a:,.0f} TKA + {amt_b:,.0f} TKB", result["new_reserves"])
                    st.session_state.s1_seed = {"a": float(amt_a), "b": float(amt_b)}
                    guided_after_tx(chain, "s1_stack")
                    st.session_state.s1_step = 2
                    st.rerun()

        elif step == 2:
            st.markdown("### Step 2: Bob Swaps TokenA → TokenB")
            st.markdown("**Bob** wants to buy TokenB using TokenA. Watch how the constant-product formula determines the output.")

            show_pool_state(dex, "Pool Before Swap")

            amt_in = st.number_input("Bob's swap amount (TKA)", value=500.0, min_value=1.0, step=100.0, key="s1_swap1")

            ra, rb = dex.get_reserves()
            ra_h, rb_h = to_h(ra), to_h(rb)
            expected = dex.quote_swap(dex.token_a_address, to_w(amt_in))
            expected_h = to_h(expected)

            st.info(f"Expected output: **{expected_h:,.4f} TKB**")

            exec_price = amt_in / expected_h if expected_h > 0 else 0
            spot = rb_h / ra_h if ra_h > 0 else 0
            impact = (exec_price - spot) / spot * 100 if spot > 0 else 0

            c1, c2, c3 = st.columns(3)
            c1.metric("Spot Price", f"{spot:,.6f}")
            c2.metric("Execution Price", f"{exec_price:,.6f}")
            c3.metric("Price Impact", f"{impact:,.2f}%")

            show_math(
                "Swap Output (Uniswap V2)",
                "Δy = (y · Δx · 997) / (x · 1000 + Δx · 997)",
                f"numerator   = {rb_h:,.0f} × {amt_in:,.0f} × 997 = {rb_h * amt_in * 997:,.0f}\n"
                f"denominator = {ra_h:,.0f} × 1000 + {amt_in:,.0f} × 997 = {ra_h * 1000 + amt_in * 997:,.0f}\n"
                f"Δy = {rb_h * amt_in * 997:,.0f} / {ra_h * 1000 + amt_in * 997:,.0f} ≈ {expected_h:,.4f}",
                f"Bob receives {expected_h:,.4f} TKB for {amt_in:,.0f} TKA"
            )

            if st.button("Bob: Execute Swap ➡️", type="primary", key="s1_exec_2"):
                bob = address_of(chain, "Bob")
                result = dex.swap(bob, dex.token_a_address, to_w(amt_in), 0)
                actual_out = result["logs_parsed"][0]["amountOut"] if result["logs_parsed"] else 0
                show_tx_receipt(result, "SimpleDEX", "swap")
                add_tx("⚪ Swap", "Bob", f"{amt_in:,.0f} TKA → {to_h(actual_out):,.4f} TKB", result["new_reserves"])
                guided_after_tx(chain, "s1_stack")
                st.session_state.s1_step = 3
                st.rerun()

        elif step == 3:
            st.markdown("### Step 3: Carol Swaps TokenB → TokenA (Reverse)")
            st.markdown("**Carol** swaps in the opposite direction. Notice how the price partially recovers.")

            show_pool_state(dex, "Pool Before Carol's Swap")

            amt_in = st.number_input("Carol's swap amount (TKB)", value=200.0, min_value=1.0, step=100.0, key="s1_swap2")
            expected = dex.quote_swap(dex.token_b_address, to_w(amt_in))
            expected_h = to_h(expected)

            st.info(f"Expected output: **{expected_h:,.4f} TKA**")

            if st.button("Carol: Execute Swap ➡️", type="primary", key="s1_exec_3"):
                carol = address_of(chain, "Carol")
                result = dex.swap(carol, dex.token_b_address, to_w(amt_in), 0)
                actual_out = result["logs_parsed"][0]["amountOut"] if result["logs_parsed"] else 0
                show_tx_receipt(result, "SimpleDEX", "swap")
                add_tx("⚪ Swap", "Carol", f"{amt_in:,.0f} TKB → {to_h(actual_out):,.4f} TKA", result["new_reserves"])
                guided_after_tx(chain, "s1_stack")
                st.session_state.s1_step = 4
                st.rerun()

        elif step == 4:
            st.markdown("### Step 4: Alice Removes 50% Liquidity")
            st.markdown("Alice withdraws half her LP shares. Because swaps generated 0.3% fees, the pool's **k** has grown. Alice gets back slightly more value than she deposited.")

            show_pool_state(dex, "Pool Before Removal")

            alice = address_of(chain, "Alice")
            alice_shares = dex.lp_shares_of(alice)
            half_shares = alice_shares // 2

            ra, rb = dex.get_reserves()
            total_lp = dex.total_lp_shares()
            receive_a = (half_shares * ra) // total_lp
            receive_b = (half_shares * rb) // total_lp

            st.markdown(f"Alice's LP shares: **{to_h(alice_shares):,.4f}** → removing **{to_h(half_shares):,.4f}**")

            c1, c2 = st.columns(2)
            c1.metric("Will receive TKA", f"{to_h(receive_a):,.4f}")
            c2.metric("Will receive TKB", f"{to_h(receive_b):,.4f}")

            seed = st.session_state.get("s1_seed") or {"a": 10000.0, "b": 10000.0}
            initial_a = seed["a"]
            initial_b = seed["b"]
            no_fee_a = initial_a / 2
            no_fee_b = initial_b / 2
            fee_profit_a = to_h(receive_a) - no_fee_a
            fee_profit_b = to_h(receive_b) - no_fee_b

            show_math(
                "Fee Earnings Comparison",
                "profit = received − (deposited × 50%)",
                f"With fees:    {to_h(receive_a):,.4f} TKA + {to_h(receive_b):,.4f} TKB\n"
                f"Without fees: {no_fee_a:,.4f} TKA + {no_fee_b:,.4f} TKB (if k stayed constant)\n"
                f"Fee profit:   {fee_profit_a:+,.4f} TKA + {fee_profit_b:+,.4f} TKB",
                f"The 0.3% fee on each swap accrued to Alice's LP position"
            )

            if st.button("Alice: Remove 50% Liquidity ➡️", type="primary", key="s1_exec_4"):
                result = dex.remove_liquidity(alice, half_shares)
                show_tx_receipt(result, "SimpleDEX", "removeLiquidity")
                add_tx("⚪ Remove", "Alice", f"Removed {to_h(half_shares):,.4f} shares", result["new_reserves"])
                guided_after_tx(chain, "s1_stack")
                st.success("✅ Mode 1 Complete! The pool state carries forward to Mode 2.")
                st.rerun()


# ---------------------------------------------------------------------------
# MODE 2: Sandwich Attack
# ---------------------------------------------------------------------------
def mode_sandwich():
    st.title("2️⃣ Sandwich Attack")
    ensure_default_pool(dex, chain)
    init_guided_stack(chain, "s2_stack")
    step = st.session_state.s2_step

    def reset_mode_2():
        stack = st.session_state.get("s2_stack", [])
        if len(stack) >= 1:
            chain.revert_to_snapshot(stack[0])
        st.session_state.s2_stack = [chain.take_snapshot()]
        st.session_state.s2_step = 0
        st.session_state.s2_data = {}
        st.rerun()

    col_l, col_r = st.columns([3, 1])
    with col_r:
        st.caption(f"Step {step}/5")
        render_guided_nav(chain, "s2_step", "s2_stack", step, reset_mode_2)

    with col_l:
        if step == 0:
            st.markdown(
                "### What is a Sandwich Attack?\n\n"
                "On Ethereum, pending transactions sit in a public **mempool** before being included in a block. "
                "An attacker (Eve) can:\n"
                "1. **See** Bob's pending swap\n"
                "2. **Front-run**: place her own swap *before* Bob's, moving the price against him\n"
                "3. **Let Bob's swap execute** at a worse price\n"
                "4. **Back-run**: reverse her position *after* Bob's, pocketing the difference\n\n"
                "Let's watch it happen step by step."
            )
            show_pool_state(dex)

            victim_amt = st.number_input("Bob's swap amount (TKA→TKB)", value=1000.0, min_value=100.0, step=100.0, key="s2_victim")
            frontrun_amt = st.number_input("Eve's front-run amount (TKA→TKB)", value=500.0, min_value=100.0, step=100.0, key="s2_frontrun")

            # Show what Bob WOULD get without attack
            fair_output = dex.quote_swap(dex.token_a_address, to_w(victim_amt))
            st.info(f"Without attack, Bob would receive: **{to_h(fair_output):,.4f} TKB**")

            st.session_state.s2_data["victim_amt"] = victim_amt
            st.session_state.s2_data["frontrun_amt"] = frontrun_amt
            st.session_state.s2_data["fair_output"] = fair_output

            if st.button("Next Step ➡️", key="s2_next_0"):
                st.session_state.s2_step = 1
                st.rerun()

        elif step == 1:
            st.markdown("### Step 1: Bob's Transaction Enters the Mempool")
            st.markdown(
                "Bob submits a swap of **{:,.0f} TKA → TKB**. His transaction is now visible "
                "in the mempool. Eve sees it and prepares her attack.".format(
                    st.session_state.s2_data["victim_amt"]
                )
            )

            st.warning("⚠️ Bob's swap is PUBLIC in the mempool. Eve can see: direction, amount, slippage tolerance.")

            # Block timeline
            st.markdown("#### Transaction Ordering (Mempool View)")
            st.markdown(
                "```\n"
                "Mempool:\n"
                "  📋 Bob: swap {:,.0f} TKA → TKB (pending)\n"
                "  👁️ Eve is watching...\n"
                "```".format(st.session_state.s2_data["victim_amt"])
            )

            if st.button("Eve: Front-run ➡️", type="primary", key="s2_exec_1"):
                eve = address_of(chain, "Eve")
                frontrun_amt = st.session_state.s2_data["frontrun_amt"]
                st.session_state.s2_data["eve_tkb_before"] = dex.balance_of(dex.token_b_address, eve)
                st.session_state.s2_data["eve_tka_before"] = dex.balance_of(dex.token_a_address, eve)
                result = dex.swap(eve, dex.token_a_address, to_w(frontrun_amt), 0)
                actual_out = result["logs_parsed"][0]["amountOut"] if result["logs_parsed"] else 0
                st.session_state.s2_data["eve_frontrun_out"] = actual_out
                add_tx("🔴 Front-run", "Eve", f"{frontrun_amt:,.0f} TKA → {to_h(actual_out):,.4f} TKB", result["new_reserves"])
                guided_after_tx(chain, "s2_stack")
                st.session_state.s2_step = 2
                st.rerun()

        elif step == 2:
            st.markdown("### Step 2: 🔴 Eve Front-runs (Block N)")
            st.markdown("Eve paid higher gas to get her transaction included **before** Bob's.")

            show_pool_state(dex, "Pool AFTER Eve's Front-run (price pushed up)")
            frontrun_amt = st.session_state.s2_data["frontrun_amt"]
            actual_out = st.session_state.s2_data["eve_frontrun_out"]
            show_math(
                "Eve's Front-run Swap",
                "Δy = (y · Δx · 997) / (x · 1000 + Δx · 997)",
                f"Eve swapped {frontrun_amt:,.0f} TKA → {to_h(actual_out):,.4f} TKB\n"
                f"(price of TKB increases for Bob)",
                f"Eve received {to_h(actual_out):,.4f} TKB",
            )

            st.markdown("#### Block Timeline")
            st.markdown(
                "```\n"
                "Block N:\n"
                "  ✅ Eve: front-run {:,.0f} TKA → {:,.4f} TKB  ← EXECUTED\n"
                "  ⏳ Bob: {:,.0f} TKA → TKB                   ← PENDING\n"
                "```".format(frontrun_amt, to_h(actual_out), st.session_state.s2_data["victim_amt"])
            )

            if st.button("Bob's Swap Executes ➡️", type="primary", key="s2_exec_2"):
                bob = address_of(chain, "Bob")
                victim_amt = st.session_state.s2_data["victim_amt"]
                result = dex.swap(bob, dex.token_a_address, to_w(victim_amt), 0)
                actual_bob = result["logs_parsed"][0]["amountOut"] if result["logs_parsed"] else 0
                st.session_state.s2_data["bob_actual"] = actual_bob
                add_tx("🟡 Victim", "Bob", f"{victim_amt:,.0f} TKA → {to_h(actual_bob):,.4f} TKB (sandwiched)", result["new_reserves"])
                guided_after_tx(chain, "s2_stack")
                st.session_state.s2_step = 3
                st.rerun()

        elif step == 3:
            st.markdown("### Step 3: 🟡 Bob's Swap Executed (Block N+1)")
            show_pool_state(dex, "Pool AFTER Bob's Swap")
            victim_amt = st.session_state.s2_data["victim_amt"]
            fair_output = st.session_state.s2_data["fair_output"]
            bob_actual = st.session_state.s2_data["bob_actual"]
            st.error(
                f"Bob got {to_h(bob_actual):,.4f} TKB vs ~{to_h(fair_output):,.4f} TKB fair. "
                f"**Loss: {to_h(fair_output - bob_actual):,.4f} TKB**"
            )
            show_math(
                "Bob's Loss from Sandwich",
                "loss = fair output − actual output",
                f"Fair output (no attack): {to_h(fair_output):,.4f} TKB\n"
                f"Actual output (attacked): {to_h(bob_actual):,.4f} TKB\n"
                f"Bob's loss: {to_h(fair_output - bob_actual):,.4f} TKB",
                f"Bob lost {to_h(fair_output - bob_actual):,.4f} TKB due to the sandwich",
            )

            if st.button("Eve: Back-run ➡️", type="primary", key="s2_exec_3"):
                eve = address_of(chain, "Eve")
                eve_frontrun_out = st.session_state.s2_data["eve_frontrun_out"]
                result = dex.swap(eve, dex.token_b_address, eve_frontrun_out, 0)
                backrun_out = result["logs_parsed"][0]["amountOut"] if result["logs_parsed"] else 0
                st.session_state.s2_data["eve_backrun_out"] = backrun_out
                add_tx("🔴 Back-run", "Eve", f"{to_h(eve_frontrun_out):,.4f} TKB → {to_h(backrun_out):,.4f} TKA", result["new_reserves"])
                guided_after_tx(chain, "s2_stack")
                st.session_state.s2_step = 4
                st.rerun()

        elif step == 4:
            st.markdown("### Step 4: 🔴 Eve Back-runs (Block N+2)")
            eve_frontrun_out = st.session_state.s2_data["eve_frontrun_out"]
            backrun_out = st.session_state.s2_data["eve_backrun_out"]

            show_pool_state(dex, "Pool AFTER Eve's Back-run")

            st.markdown("#### Complete Block Timeline")
            st.markdown(
                "```\n"
                "Block N:   🔴 Eve front-run  {:,.0f} TKA → {:,.4f} TKB\n"
                "Block N+1: 🟡 Bob victim     {:,.0f} TKA → {:,.4f} TKB\n"
                "Block N+2: 🔴 Eve back-run   {:,.4f} TKB → {:,.4f} TKA\n"
                "```".format(
                    st.session_state.s2_data["frontrun_amt"],
                    to_h(eve_frontrun_out),
                    st.session_state.s2_data["victim_amt"],
                    to_h(st.session_state.s2_data["bob_actual"]),
                    to_h(eve_frontrun_out),
                    to_h(backrun_out),
                )
            )

            if st.button("See Summary ➡️", type="primary", key="s2_exec_4"):
                st.session_state.s2_step = 5
                st.rerun()

        elif step == 5:
            st.markdown("### Step 5: Attack Summary")

            frontrun_amt = st.session_state.s2_data["frontrun_amt"]
            backrun_out = st.session_state.s2_data["eve_backrun_out"]
            eve_profit_tka = to_h(backrun_out) - frontrun_amt
            fair_output = st.session_state.s2_data["fair_output"]
            bob_actual = st.session_state.s2_data["bob_actual"]
            bob_loss = to_h(fair_output) - to_h(bob_actual)

            c1, c2 = st.columns(2)
            with c1:
                st.error("🔴 Eve's Profit")
                st.metric("TKA spent", f"{frontrun_amt:,.4f}")
                st.metric("TKA received back", f"{to_h(backrun_out):,.4f}")
                st.metric("Net profit (TKA)", f"{eve_profit_tka:+,.4f}")

            with c2:
                st.warning("🟡 Bob's Loss")
                st.metric("Expected TKB (fair)", f"{to_h(fair_output):,.4f}")
                st.metric("Actual TKB (sandwiched)", f"{to_h(bob_actual):,.4f}")
                st.metric("Loss (TKB)", f"{bob_loss:,.4f}")

            show_math(
                "Sandwich Attack Economics",
                "Eve profit ≈ Bob loss − fees to pool",
                f"Eve's profit: {eve_profit_tka:+,.4f} TKA\n"
                f"Bob's loss:   {bob_loss:,.4f} TKB\n"
                f"The difference goes to LP fee (0.3% × 3 swaps)",
                "The attacker extracts value from the victim by manipulating the execution price.",
            )

            st.success("✅ Mode 2 Complete! Proceed to Mode 3 to see how Commit-Reveal defends against this attack.")


# ---------------------------------------------------------------------------
# MODE 3: Commit-Reveal Defense
# ---------------------------------------------------------------------------
def mode_commit_reveal():
    st.title("3️⃣ Commit-Reveal Defense")
    ensure_default_pool(dex, chain)
    init_guided_stack(chain, "s3_stack")
    step = st.session_state.s3_step

    def reset_mode_3():
        stack = st.session_state.get("s3_stack", [])
        if len(stack) >= 1:
            chain.revert_to_snapshot(stack[0])
        st.session_state.s3_stack = [chain.take_snapshot()]
        st.session_state.s3_step = 0
        st.session_state.s3_data = {}
        st.rerun()

    col_l, col_r = st.columns([3, 1])
    with col_r:
        st.caption(f"Step {step}/5")
        render_guided_nav(chain, "s3_step", "s3_stack", step, reset_mode_3)

    ensure_cr_pool_synced(dex, cr_dex, chain)

    with col_l:
        if step == 0:
            st.markdown(
                "### How Commit-Reveal Works\n\n"
                "The idea: **hide your trade details** until it's too late for anyone to front-run.\n\n"
                "1. **Commit**: Submit `hash(tokenIn, amountIn, amountOutMin, secret)` — "
                "the chain sees only a hash, not the trade parameters.\n"
                "2. **Wait one block** — ensures the commit is mined before the reveal.\n"
                "3. **Reveal**: Submit the original parameters + secret. The contract verifies the hash "
                "matches, then executes the swap.\n\n"
                "Since Eve can't see the trade direction or amount during the commit phase, she can't sandwich."
            )
            show_pool_state(cr_dex, "CommitReveal DEX Pool State")

            victim_amt = st.number_input("Bob's swap amount (TKA→TKB)", value=1000.0, min_value=100.0, step=100.0, key="s3_amt")
            st.session_state.s3_data["victim_amt"] = victim_amt

            if st.button("Next Step ➡️", key="s3_next_0"):
                st.session_state.s3_step = 1
                st.rerun()

        elif step == 1:
            st.markdown("### Step 1: Bob Commits His Swap")
            victim_amt = st.session_state.s3_data["victim_amt"]

            bob = address_of(chain, "Bob")
            secret = b"\x01" * 32

            commit_hash = cr_dex.compute_commit_hash(
                cr_dex.token_a_address, to_w(victim_amt), 0, secret
            )
            st.session_state.s3_data["secret"] = secret
            st.session_state.s3_data["commit_hash"] = commit_hash

            st.markdown(f"Bob's trade: **{victim_amt:,.0f} TKA → TKB**")
            st.code(f"commit_hash = keccak256(tokenA, {victim_amt:,.0f}, 0, secret)\n           = {commit_hash.hex()}")
            st.info("On-chain, only the hash is visible. Eve cannot determine direction, amount, or token.")

            if st.button("Bob: Submit commit (mine block) ➡️", type="primary", key="s3_exec_commit"):
                cr_dex.commit_swap(bob, commit_hash)
                add_tx("🔒 Commit", "Bob", f"Hash: {commit_hash.hex()[:16]}...", cr_dex.get_reserves())
                chain.mine_block()
                guided_after_tx(chain, "s3_stack")
                st.session_state.s3_step = 2
                st.rerun()

        elif step == 2:
            st.markdown("### Step 2: Eve's Blind Attack Attempt")
            st.markdown(
                "Eve sees Bob's commit hash but **cannot decode it**. "
                "She decides to gamble and front-run anyway, guessing Bob is buying TKB."
            )

            guess_amt = 300.0
            st.warning(f"Eve guesses: swap {guess_amt:,.0f} TKA → TKB (but she's not sure of Bob's direction!)")

            show_pool_state(cr_dex, "Pool Before Eve's Guess")

            if st.button("Eve: Execute blind front-run ➡️", type="primary", key="s3_exec_eve_guess"):
                eve = address_of(chain, "Eve")
                result = cr_dex.swap(eve, cr_dex.token_a_address, to_w(guess_amt), 0)
                eve_got = result["logs_parsed"][0]["amountOut"] if result["logs_parsed"] else 0
                st.session_state.s3_data["eve_guess_out"] = eve_got
                st.session_state.s3_data["eve_guess_amt"] = guess_amt
                add_tx("🔴 Blind Attack", "Eve", f"{guess_amt:,.0f} TKA → {to_h(eve_got):,.4f} TKB (blind guess)", result["new_reserves"])
                guided_after_tx(chain, "s3_stack")
                st.session_state.s3_step = 3
                st.rerun()

        elif step == 3:
            st.markdown("### Step 3: Bob Reveals and Swap Executes")
            show_pool_state(cr_dex, "Pool Before Bob's Reveal")

            if st.button("Bob: Reveal + execute swap ➡️", type="primary", key="s3_exec_reveal"):
                bob = address_of(chain, "Bob")
                victim_amt = st.session_state.s3_data["victim_amt"]
                secret = st.session_state.s3_data["secret"]
                chain.mine_block()
                result = cr_dex.reveal_swap(
                    bob, cr_dex.token_a_address, to_w(victim_amt), 0, secret
                )
                bob_got = result["logs_parsed"][0]["amountOut"] if result["logs_parsed"] else 0
                st.session_state.s3_data["bob_got_cr"] = bob_got
                add_tx("🔓 Reveal+Swap", "Bob", f"{victim_amt:,.0f} TKA → {to_h(bob_got):,.4f} TKB", result["new_reserves"])
                guided_after_tx(chain, "s3_stack")
                st.session_state.s3_step = 4
                st.rerun()

        elif step == 4:
            st.markdown("### Step 4: Eve Tries to Back-run (Too Late)")
            show_pool_state(cr_dex, "Pool After Bob's Reveal")

            if st.button("Eve: Sell TKB back ➡️", type="primary", key="s3_exec_eve_back"):
                eve = address_of(chain, "Eve")
                eve_got = st.session_state.s3_data["eve_guess_out"]
                result = cr_dex.swap(eve, cr_dex.token_b_address, eve_got, 0)
                eve_back = result["logs_parsed"][0]["amountOut"] if result["logs_parsed"] else 0
                st.session_state.s3_data["eve_back"] = eve_back
                guess_amt = st.session_state.s3_data["eve_guess_amt"]
                eve_loss = guess_amt - to_h(eve_back)
                add_tx("🔴 Failed Back-run", "Eve", f"{to_h(eve_got):,.4f} TKB → {to_h(eve_back):,.4f} TKA (loss)", result["new_reserves"])
                guided_after_tx(chain, "s3_stack")
                st.session_state.s3_step = 5
                st.rerun()

        elif step == 5:
            st.markdown("### Step 5: Comparison — With vs Without Commit-Reveal")

            victim_amt = st.session_state.s3_data["victim_amt"]
            bob_got_cr = st.session_state.s3_data.get("bob_got_cr", 0)
            bob_sandwiched = st.session_state.s2_data.get("bob_actual", 0)
            fair_output = st.session_state.s2_data.get("fair_output", 0)

            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown("**No Attack**")
                st.metric("Bob gets", f"{to_h(fair_output):,.4f} TKB" if fair_output else "N/A")
            with c2:
                st.markdown("**Sandwiched (Mode 2)**")
                st.metric("Bob gets", f"{to_h(bob_sandwiched):,.4f} TKB" if bob_sandwiched else "N/A")
            with c3:
                st.markdown("**Commit-Reveal (Mode 3)**")
                st.metric("Bob gets", f"{to_h(bob_got_cr):,.4f} TKB")

            eve_guess_amt = st.session_state.s3_data.get("eve_guess_amt", 0)
            eve_back = st.session_state.s3_data.get("eve_back", 0)
            eve_result = to_h(eve_back) - eve_guess_amt if eve_back else 0

            st.markdown("---")
            st.markdown(f"**Eve's result in Mode 3:** {eve_result:+,.4f} TKA (blind guess penalty)")
            st.success(
                "✅ Mode 3 Complete! Commit-Reveal prevents sandwich attacks by hiding trade details. "
                "But it has a vulnerability — proceed to Mode 4 to discover it."
            )


# ---------------------------------------------------------------------------
# MODE 4: Last Revealer Attack
# ---------------------------------------------------------------------------
def mode_last_revealer():
    st.title("4️⃣ Last Revealer Attack")
    ensure_default_pool(dex, chain)
    ensure_cr_pool_synced(dex, cr_dex, chain)
    init_guided_stack(chain, "s4_stack")
    step = st.session_state.s4_step

    def reset_mode_4():
        stack = st.session_state.get("s4_stack", [])
        if len(stack) >= 1:
            chain.revert_to_snapshot(stack[0])
        st.session_state.s4_stack = [chain.take_snapshot()]
        st.session_state.s4_step = 0
        st.session_state.s4_data = {}
        st.rerun()

    col_l, col_r = st.columns([3, 1])
    with col_r:
        st.caption(f"Step {step}/5")
        render_guided_nav(chain, "s4_step", "s4_stack", step, reset_mode_4)

    with col_l:
        if step == 0:
            st.markdown(
                "### The Last Revealer Problem\n\n"
                "Commit-Reveal has a subtle vulnerability: when multiple traders commit, "
                "they must reveal **one at a time**. The **last person to reveal** gets to:\n\n"
                "1. See everyone else's revealed trades\n"
                "2. Decide whether to reveal their own trade — or simply **walk away** (griefing)\n\n"
                "Eve exploits this by committing a trade, waiting for others to reveal, "
                "then choosing NOT to reveal if the information is unfavorable — "
                "wasting the commit gas but avoiding a bad trade."
            )
            show_pool_state(cr_dex)
            if st.button("Next Step ➡️", key="s4_next_0"):
                st.session_state.s4_step = 1
                st.rerun()

        elif step == 1:
            st.markdown("### Step 1: Alice and Bob Both Commit")

            alice = address_of(chain, "Alice")
            bob = address_of(chain, "Bob")

            alice_amt = st.number_input("Alice's swap (TKA→TKB)", value=800.0, min_value=100.0, step=100.0, key="s4_alice")
            bob_amt = st.number_input("Bob's swap (TKA→TKB)", value=600.0, min_value=100.0, step=100.0, key="s4_bob")

            secret_a = b'\x0a' * 32
            secret_b = b'\x0b' * 32

            hash_a = cr_dex.compute_commit_hash(cr_dex.token_a_address, to_w(alice_amt), 0, secret_a)
            hash_b = cr_dex.compute_commit_hash(cr_dex.token_a_address, to_w(bob_amt), 0, secret_b)

            st.session_state.s4_data.update({
                "alice_amt": alice_amt, "bob_amt": bob_amt,
                "secret_a": secret_a, "secret_b": secret_b,
                "hash_a": hash_a, "hash_b": hash_b,
            })

            if st.button("Commit Both ➡️", type="primary", key="s4_exec_1"):
                cr_dex.commit_swap(alice, hash_a)
                cr_dex.commit_swap(bob, hash_b)
                chain.mine_block()
                add_tx("🔒 Commit", "Alice", f"Hash: {hash_a.hex()[:16]}...", cr_dex.get_reserves())
                add_tx("🔒 Commit", "Bob", f"Hash: {hash_b.hex()[:16]}...", cr_dex.get_reserves())
                guided_after_tx(chain, "s4_stack")
                st.session_state.s4_step = 2
                st.rerun()

        elif step == 2:
            st.markdown("### Step 2: Alice Reveals First")

            alice = address_of(chain, "Alice")
            alice_amt = st.session_state.s4_data["alice_amt"]
            secret_a = st.session_state.s4_data["secret_a"]

            if st.button("Alice: Reveal swap ➡️", type="primary", key="s4_exec_alice_rev"):
                chain.mine_block()
                result = cr_dex.reveal_swap(
                    alice, cr_dex.token_a_address, to_w(alice_amt), 0, secret_a
                )
                alice_got = result["logs_parsed"][0]["amountOut"] if result["logs_parsed"] else 0
                st.session_state.s4_data["alice_got"] = alice_got
                add_tx("🔓 Reveal", "Alice", f"{alice_amt:,.0f} TKA → {to_h(alice_got):,.4f} TKB", result["new_reserves"])
                guided_after_tx(chain, "s4_stack")
                st.session_state.s4_step = 3
                st.rerun()

        elif step == 3:
            st.markdown("### Step 3: Eve Sees Alice's Trade — Decides Not to Reveal")
            alice_amt = st.session_state.s4_data["alice_amt"]
            alice_got = st.session_state.s4_data.get("alice_got", 0)
            st.success(f"Alice revealed: {alice_amt:,.0f} TKA → {to_h(alice_got):,.4f} TKB")
            st.warning("⚠️ Alice's trade details are now PUBLIC. Anyone who hasn't revealed yet can see them.")
            show_pool_state(cr_dex, "Pool After Alice's Reveal")
            st.markdown(
                "Eve also committed a trade earlier. Now she sees Alice bought TKB, "
                "which moved the price. Eve has two options:\n\n"
                "- **Reveal**: Execute her committed trade at the current (worse) price\n"
                "- **Don't reveal**: Abandon her commit, losing only the commit gas fee\n\n"
                "Eve chooses to **not reveal** — a rational but adversarial choice."
            )

            st.error(
                "🛑 Eve chooses to GRIEF: she abandons her commitment.\n"
                "She loses the gas fee for the commit (~21,000 gas) but avoids a bad trade.\n"
                "This is the **Last Revealer Attack** — the ability to act on information "
                "that other participants don't have."
            )

            if st.button("Bob Reveals ➡️", type="primary", key="s4_exec_3"):
                st.session_state.s4_step = 4
                st.rerun()

        elif step == 4:
            st.markdown("### Step 4: Bob Reveals (Unaware of the Problem)")
            show_pool_state(cr_dex, "Pool Before Bob's Reveal")

            if st.button("Bob: Reveal swap ➡️", type="primary", key="s4_exec_bob_rev"):
                bob = address_of(chain, "Bob")
                bob_amt = st.session_state.s4_data["bob_amt"]
                secret_b = st.session_state.s4_data["secret_b"]
                chain.mine_block()
                result = cr_dex.reveal_swap(
                    bob, cr_dex.token_a_address, to_w(bob_amt), 0, secret_b
                )
                bob_got = result["logs_parsed"][0]["amountOut"] if result["logs_parsed"] else 0
                st.session_state.s4_data["bob_got"] = bob_got
                add_tx("🔓 Reveal", "Bob", f"{bob_amt:,.0f} TKA → {to_h(bob_got):,.4f} TKB", result["new_reserves"])
                guided_after_tx(chain, "s4_stack")
                st.session_state.s4_step = 5
                st.rerun()

        elif step == 5:
            st.markdown("### Step 5: Summary — The Last Revealer Advantage")
            bob_got = st.session_state.s4_data.get("bob_got", 0)
            st.info(f"Bob received: **{to_h(bob_got):,.4f} TKB**")
            show_pool_state(cr_dex, "Pool After Bob's Reveal")

            st.markdown(
                "**The problem**: In commit-reveal, participants reveal sequentially. "
                "The last revealer gains an **information asymmetry** — they see others' trades "
                "and can choose to act or abstain.\n\n"
                "**Damage types**:\n"
                "- **Griefing**: Refuse to reveal, wasting only gas but denying others fair execution\n"
                "- **Strategic delay**: Wait to reveal until favorable, or selectively abandon\n\n"
                "**Commit-Reveal solves**: External attacker (Eve can't sandwich from outside)\n"
                "**Commit-Reveal fails**: Participant-level information leakage during reveal phase"
            )

            st.success(
                "✅ Mode 4 Complete! Proceed to Mode 5 to see how Threshold Encryption "
                "eliminates the last-revealer problem by decrypting all orders simultaneously."
            )


# ---------------------------------------------------------------------------
# MODE 5: Threshold Encryption
# ---------------------------------------------------------------------------
def mode_threshold():
    st.title("5️⃣ Threshold Encryption (Batch Execution)")
    ensure_default_pool(dex, chain)
    init_guided_stack(chain, "s5_stack")
    step = st.session_state.s5_step

    def reset_mode_5():
        stack = st.session_state.get("s5_stack", [])
        if len(stack) >= 1:
            chain.revert_to_snapshot(stack[0])
        st.session_state.s5_stack = [chain.take_snapshot()]
        st.session_state.s5_step = 0
        st.session_state.s5_data = {}
        th_dex.reset_batch(chain.accounts[0])
        st.rerun()

    col_l, col_r = st.columns([3, 1])
    with col_r:
        st.caption(f"Step {step}/4")
        render_guided_nav(chain, "s5_step", "s5_stack", step, reset_mode_5)

    ra, rb = dex.get_reserves()
    tha, thb = th_dex.get_reserves()
    if ra > 0 and rb > 0 and tha == 0 and thb == 0:
        th_dex.add_liquidity(chain.accounts[0], ra, rb)

    with col_l:
        if step == 0:
            st.markdown(
                "### How Threshold Encryption Works\n\n"
                "The core idea: **nobody can read any order until ALL orders are decrypted at once**.\n\n"
                "In a real system, this uses **threshold cryptography**: a decryption key is split "
                "among *k-of-n* key holders. The key only becomes available when enough holders "
                "collaborate — which they're incentivized to do only after the submission window closes.\n\n"
                "**The result**: All orders are revealed and executed in a single atomic batch. "
                "No participant can see or react to others' orders. The last-revealer problem is eliminated."
            )

            st.markdown(
                "#### Visualization: The Black Box\n\n"
                "```\n"
                "┌─────────── SUBMISSION WINDOW (OPEN) ───────────┐\n"
                "│                                                  │\n"
                "│  Alice: [████████████] (encrypted)               │\n"
                "│  Bob:   [████████████] (encrypted)               │\n"
                "│  Eve:   [████████████] (encrypted)               │\n"
                "│                                                  │\n"
                "│  Nobody can read anyone's order — not even       │\n"
                "│  the validators or block producers.              │\n"
                "│                                                  │\n"
                "└──────────────────────────────────────────────────┘\n"
                "                    ↓ Time lock expires\n"
                "┌─────────── BATCH EXECUTION ────────────────────┐\n"
                "│                                                  │\n"
                "│  🔓 All orders decrypted simultaneously          │\n"
                "│  📋 Sorted deterministically (by address)        │\n"
                "│  ⚡ Executed atomically in one transaction        │\n"
                "│                                                  │\n"
                "└──────────────────────────────────────────────────┘\n"
                "```"
            )

            show_pool_state(th_dex, "Threshold DEX Pool State")

            if st.button("Next Step ➡️", key="s5_next_0"):
                st.session_state.s5_step = 1
                st.rerun()

        elif step == 1:
            st.markdown("### Step 1: Everyone Submits Encrypted Orders")

            alice = address_of(chain, "Alice")
            bob = address_of(chain, "Bob")
            eve = address_of(chain, "Eve")

            alice_amt = st.number_input("Alice's swap (TKA→TKB)", value=500.0, min_value=100.0, step=100.0, key="s5_alice")
            bob_amt = st.number_input("Bob's swap (TKA→TKB)", value=300.0, min_value=100.0, step=100.0, key="s5_bob")
            eve_amt = st.number_input("Eve's swap (TKB→TKA)", value=400.0, min_value=100.0, step=100.0, key="s5_eve")

            secret_a = b'\xaa' * 32
            secret_b = b'\xbb' * 32
            secret_e = b'\xee' * 32

            hash_a = th_dex.compute_commit_hash(th_dex.token_a_address, to_w(alice_amt), 0, secret_a)
            hash_b = th_dex.compute_commit_hash(th_dex.token_a_address, to_w(bob_amt), 0, secret_b)
            hash_e = th_dex.compute_commit_hash(th_dex.token_b_address, to_w(eve_amt), 0, secret_e)

            st.session_state.s5_data.update({
                "alice_amt": alice_amt, "bob_amt": bob_amt, "eve_amt": eve_amt,
                "secret_a": secret_a, "secret_b": secret_b, "secret_e": secret_e,
                "hash_a": hash_a, "hash_b": hash_b, "hash_e": hash_e,
            })

            if st.button("Submit All Orders ➡️", type="primary", key="s5_exec_1"):
                th_dex.submit_encrypted_order(alice, hash_a)
                th_dex.submit_encrypted_order(bob, hash_b)
                th_dex.submit_encrypted_order(eve, hash_e)

                add_tx("🔐 Encrypted Submit", "Alice", f"[encrypted order] hash: {hash_a.hex()[:16]}...", th_dex.get_reserves())
                add_tx("🔐 Encrypted Submit", "Bob", f"[encrypted order] hash: {hash_b.hex()[:16]}...", th_dex.get_reserves())
                add_tx("🔐 Encrypted Submit", "Eve", f"[encrypted order] hash: {hash_e.hex()[:16]}...", th_dex.get_reserves())

                guided_after_tx(chain, "s5_stack")
                st.session_state.s5_step = 2
                st.rerun()

        elif step == 2:
            st.markdown("### Step 2: Submission Window Closes — Batch Decryption")
            st.markdown(
                "The time lock expires. In a real system, the threshold key holders would now "
                "collaborate to produce the decryption key. In our simulation, we proceed directly "
                "to batch decryption and execution."
            )

            st.markdown(
                "```\n"
                "🔒 Submission window CLOSED\n"
                "⏳ Decryption ceremony in progress...\n"
                "   - Key share 1/3 ✅\n"
                "   - Key share 2/3 ✅\n"
                "   - Key share 3/3 ✅\n"
                "🔓 Threshold reached! All orders decrypted simultaneously.\n"
                "```"
            )

            show_pool_state(th_dex, "Pool BEFORE Batch Execution")

            if st.button("Execute Batch ➡️", type="primary", key="s5_exec_2"):
                deployer = chain.accounts[0]
                th_dex.close_submission_window(deployer)

                alice = address_of(chain, "Alice")
                bob = address_of(chain, "Bob")
                eve = address_of(chain, "Eve")

                d = st.session_state.s5_data
                result = th_dex.batch_decrypt_and_execute(
                    deployer,
                    traders=[alice, bob, eve],
                    token_ins=[th_dex.token_a_address, th_dex.token_a_address, th_dex.token_b_address],
                    amount_ins=[to_w(d["alice_amt"]), to_w(d["bob_amt"]), to_w(d["eve_amt"])],
                    amount_out_mins=[0, 0, 0],
                    secrets=[d["secret_a"], d["secret_b"], d["secret_e"]],
                )

                st.session_state.s5_data["batch_result"] = result
                for log in result.get("exec_logs", []):
                    trader_name = chain.get_account_name(log["trader"])
                    add_tx(
                        "🔐 Batch Execute", trader_name,
                        f"{to_h(log['amountIn']):,.4f} → {to_h(log['amountOut']):,.4f}",
                        result["new_reserves"]
                    )

                guided_after_tx(chain, "s5_stack")
                st.session_state.s5_step = 3
                st.rerun()

        elif step == 3:
            st.markdown("### Step 3: Batch Execution Results")

            show_pool_state(th_dex, "Pool AFTER Batch Execution")

            result = st.session_state.s5_data.get("batch_result", {})
            exec_logs = result.get("exec_logs", [])

            if exec_logs:
                st.markdown("#### Executed Orders (deterministic order)")
                for i, log in enumerate(exec_logs):
                    name = chain.get_account_name(log["trader"])
                    token_dir = "TKA→TKB" if log["tokenIn"].lower() == th_dex.token_a_address.lower() else "TKB→TKA"
                    st.markdown(
                        f"**{i+1}. {name}**: {to_h(log['amountIn']):,.4f} {token_dir} → {to_h(log['amountOut']):,.4f}"
                    )

            st.markdown(
                "#### Key Insight\n\n"
                "All three orders were executed in a single atomic transaction. "
                "No participant could see or react to others' orders before execution. "
                "Even Eve — who in Mode 2 would have sandwiched Bob — executed her trade "
                "without any information advantage."
            )

            if st.button("See Final Comparison ➡️", type="primary", key="s5_exec_3"):
                st.session_state.s5_step = 4
                st.rerun()

        elif step == 4:
            st.markdown("### Step 4: Security Evolution Summary")

            st.markdown(
                "| Defense Level | Mechanism | Protects Against | Weakness |\n"
                "|---|---|---|---|\n"
                "| **None** (Mode 1-2) | Open mempool | — | Sandwich attacks |\n"
                "| **Commit-Reveal** (Mode 3) | Hash commitment | External front-running | Last revealer griefing |\n"
                "| **Threshold Encryption** (Mode 5) | Batch decryption | All ordering attacks | Coordinator trust / complexity |"
            )

            st.markdown(
                "#### Trade-offs\n\n"
                "Each defense adds latency and complexity:\n"
                "- **No defense**: 1 tx, instant execution, fully vulnerable\n"
                "- **Commit-Reveal**: 2 tx (commit + reveal), 1+ block delay\n"
                "- **Threshold Encryption**: Submission window + decryption ceremony, requires trusted key holders\n\n"
                "In production, protocols like **MEV-Share**, **Flashbots Protect**, and **threshold-encrypted mempools** "
                "(e.g., Shutter Network) implement variations of these concepts."
            )

            st.success("✅ All scenarios complete! Use Mode 6 (Free Mode) to explore further.")


# ---------------------------------------------------------------------------
# MODE 6: Free Mode
# ---------------------------------------------------------------------------
def mode_free():
    st.title("6️⃣ Free Mode")
    user_addr = st.session_state.current_user

    tab_pool, tab_swap, tab_liq, tab_hist = st.tabs(["Pool", "Swap", "Liquidity", "History"])

    with tab_pool:
        show_pool_state(dex)
        st.divider()
        total_lp = dex.total_lp_shares()
        user_lp = dex.lp_shares_of(user_addr)
        c1, c2 = st.columns(2)
        c1.metric("Total LP Shares", f"{to_h(total_lp):,.4f}")
        c2.metric("Your LP Shares", f"{to_h(user_lp):,.4f}")

    with tab_swap:
        ra, rb = dex.get_reserves()
        if ra == 0 or rb == 0:
            st.warning("Pool is empty. Add liquidity first.")
        else:
            direction = st.radio("Direction", ["TokenA → TokenB", "TokenB → TokenA"], key="fm_dir")
            token_in = dex.token_a_address if "A → B" in direction else dex.token_b_address
            token_in_name = "TKA" if "A → B" in direction else "TKB"
            token_out_name = "TKB" if "A → B" in direction else "TKA"

            bal = dex.balance_of(token_in, user_addr)
            amt = st.number_input(f"Amount ({token_in_name})", 0.0, to_h(bal), 0.0, 100.0, "%.4f", key="fm_amt")

            if amt > 0:
                exp = dex.quote_swap(token_in, to_w(amt))
                st.info(f"Expected: {to_h(exp):,.4f} {token_out_name}")
                slippage = st.slider("Slippage %", 0.1, 5.0, 0.5, 0.1, key="fm_slip")
                out_min = int(exp * (1 - slippage / 100))

                if st.button("Swap", type="primary", key="fm_swap"):
                    try:
                        r = dex.swap(user_addr, token_in, to_w(amt), out_min)
                        out = r["logs_parsed"][0]["amountOut"] if r["logs_parsed"] else 0
                        add_tx("⚪ Swap", st.session_state.current_user_name,
                               f"{amt:,.4f} {token_in_name} → {to_h(out):,.4f} {token_out_name}", r["new_reserves"])
                        st.success(f"Swapped! Got {to_h(out):,.4f} {token_out_name}")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

    with tab_liq:
        sub_add, sub_rm = st.tabs(["Add", "Remove"])
        with sub_add:
            ra, rb = dex.get_reserves()
            if ra == 0:
                a = st.number_input("TKA", 0.0, step=100.0, key="fm_la")
                b = st.number_input("TKB", 0.0, step=100.0, key="fm_lb")
                if st.button("Seed Pool", type="primary", key="fm_seed"):
                    if a > 0 and b > 0:
                        r = dex.add_liquidity(user_addr, to_w(a), to_w(b))
                        add_tx("⚪ Seed", st.session_state.current_user_name, f"{a:,.0f} TKA + {b:,.0f} TKB", r["new_reserves"])
                        st.rerun()
            else:
                a = st.number_input("TKA amount", 0.0, step=100.0, key="fm_la2")
                if a > 0:
                    req_b = (to_w(a) * rb) // ra
                    st.metric("Required TKB", f"{to_h(req_b):,.4f}")
                    if st.button("Add Liquidity", type="primary", key="fm_add"):
                        try:
                            r = dex.add_liquidity(user_addr, to_w(a), req_b)
                            add_tx("⚪ Add", st.session_state.current_user_name, f"{a:,.0f} TKA + {to_h(req_b):,.0f} TKB", r["new_reserves"])
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))
        with sub_rm:
            shares = dex.lp_shares_of(user_addr)
            if shares == 0:
                st.warning("No LP shares.")
            else:
                pct = st.slider("% to remove", 0, 100, 0, key="fm_rm_pct")
                if pct > 0:
                    rm = shares * pct // 100
                    ra, rb = dex.get_reserves()
                    tlp = dex.total_lp_shares()
                    st.write(f"Receive: {to_h(rm * ra // tlp):,.4f} TKA + {to_h(rm * rb // tlp):,.4f} TKB")
                    if st.button("Remove", type="primary", key="fm_rm"):
                        r = dex.remove_liquidity(user_addr, rm)
                        add_tx("⚪ Remove", st.session_state.current_user_name, f"Removed {pct}% shares", r["new_reserves"])
                        st.rerun()

    with tab_hist:
        render_history()


def render_history():
    """Shared transaction history renderer."""
    if not st.session_state.tx_history:
        st.info("No transactions yet.")
        return

    # Filter
    all_tags = sorted(set(tx["tag"] for tx in st.session_state.tx_history))
    selected = st.multiselect("Filter by tag", all_tags, default=all_tags, key="hist_filter")

    for i, tx in enumerate(st.session_state.tx_history):
        if tx["tag"] not in selected:
            continue
        ra_h = to_h(tx["reserves"][0]) if tx.get("reserves") else "?"
        rb_h = to_h(tx["reserves"][1]) if tx.get("reserves") else "?"
        with st.expander(
            f"{tx['tag']} | {tx['user']} | {tx['time']}: {tx['details'][:60]}",
            expanded=(i == 0),
        ):
            st.write(f"**Details:** {tx['details']}")
            st.write(f"**Pool after:** {ra_h:,.4f} TKA / {rb_h:,.4f} TKB")


# ---------------------------------------------------------------------------
# MAIN ROUTING
# ---------------------------------------------------------------------------
mode = st.session_state.get("current_mode", None)

if mode is None:
    page_overview()
elif mode in ("1", "6") and st.session_state.current_user is None:
    page_character_select()
else:
    st.sidebar.markdown(f"**Mode {mode}**")
    if mode in ("1", "6"):
        st.sidebar.markdown(f"Account: **{st.session_state.current_user_name}**")
        st.sidebar.caption(short(st.session_state.current_user))
        if st.sidebar.button("Logout / switch account"):
            st.session_state.current_user = None
            st.session_state.current_user_name = None
            st.rerun()
        st.sidebar.divider()
        bal_a = dex.balance_of(dex.token_a_address, st.session_state.current_user)
        bal_b = dex.balance_of(dex.token_b_address, st.session_state.current_user)
        lp = dex.lp_shares_of(st.session_state.current_user)
        st.sidebar.metric("TKA", f"{to_h(bal_a):,.2f}")
        st.sidebar.metric("TKB", f"{to_h(bal_b):,.2f}")
        st.sidebar.metric("LP Shares", f"{to_h(lp):,.4f}")
    else:
        st.sidebar.caption("Guided mode — no login required")

    st.sidebar.divider()
    if st.sidebar.button("← Back to overview"):
        st.session_state.current_mode = None
        st.session_state.current_user = None
        st.session_state.current_user_name = None
        st.rerun()

    if mode == "1":
        mode_simple_dex()
    elif mode == "2":
        mode_sandwich()
    elif mode == "3":
        mode_commit_reveal()
    elif mode == "4":
        mode_last_revealer()
    elif mode == "5":
        mode_threshold()
    elif mode == "6":
        mode_free()
    else:
        page_overview()
