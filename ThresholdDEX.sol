// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IERC20Minimal {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function transfer(address to, uint256 amount) external returns (bool);
}

/**
 * ThresholdDEX simulates threshold encryption for teaching purposes.
 *
 * Concept: All traders submit encrypted orders (commitments) during a submission
 * window. After the window closes, a "decryption ceremony" reveals all orders
 * simultaneously. Orders are then executed in a deterministic (alphabetical by
 * address) order — no participant can see or react to others' orders before
 * execution.
 *
 * This contract simulates the concept with a commit + batch-reveal pattern:
 * - submitEncryptedOrder(): stores a hash (simulating encryption)
 * - batchDecryptAndExecute(): coordinator reveals all orders at once
 *
 * In a real system, threshold encryption (e.g., BLS threshold) would replace
 * the coordinator role — decryption only happens when k-of-n key holders
 * collaborate.
 */
contract ThresholdDEX {
    address public tokenA;
    address public tokenB;
    uint256 public reserveA;
    uint256 public reserveB;

    mapping(address => uint256) public lpShares;
    uint256 public totalLPShares;

    // Batch state
    enum BatchPhase { SUBMISSION, CLOSED, EXECUTED }
    BatchPhase public currentPhase;
    uint256 public batchId;

    struct EncryptedOrder {
        bytes32 commitHash;
        address trader;
        bool exists;
    }

    // Current batch pending orders (by trader address)
    mapping(address => EncryptedOrder) public pendingOrders;
    address[] public pendingTraders;

    // Execution results for the last batch
    struct ExecutionResult {
        address trader;
        address tokenIn;
        uint256 amountIn;
        uint256 amountOut;
        bool success;
    }

    ExecutionResult[] public lastBatchResults;

    event LiquidityAdded(address indexed provider, uint256 amountA, uint256 amountB, uint256 sharesMinted);
    event LiquidityRemoved(address indexed provider, uint256 amountA, uint256 amountB, uint256 sharesBurned);
    event Swap(address indexed trader, address tokenIn, uint256 amountIn, uint256 amountOut);
    event OrderSubmitted(address indexed trader, bytes32 commitHash, uint256 batchId);
    event BatchDecrypted(uint256 batchId, uint256 orderCount);
    event BatchOrderExecuted(uint256 batchId, address indexed trader, address tokenIn, uint256 amountIn, uint256 amountOut);

    constructor(address _tokenA, address _tokenB) {
        tokenA = _tokenA;
        tokenB = _tokenB;
        currentPhase = BatchPhase.SUBMISSION;
        batchId = 1;
    }

    function _sqrt(uint256 y) internal pure returns (uint256 z) {
        if (y > 3) {
            z = y;
            uint256 x = y / 2 + 1;
            while (x < z) {
                z = x;
                x = (y / x + x) / 2;
            }
        } else if (y != 0) {
            z = 1;
        }
    }

    function addLiquidity(uint256 amountA, uint256 amountB) external returns (uint256 sharesMinted) {
        require(amountA > 0 && amountB > 0, "amounts must be > 0");

        if (totalLPShares == 0) {
            sharesMinted = _sqrt(amountA * amountB);
        } else {
            require(amountA * reserveB == amountB * reserveA, "ratio mismatch");
            sharesMinted = (amountA * totalLPShares) / reserveA;
        }

        require(sharesMinted > 0, "insufficient liquidity minted");

        IERC20Minimal(tokenA).transferFrom(msg.sender, address(this), amountA);
        IERC20Minimal(tokenB).transferFrom(msg.sender, address(this), amountB);

        reserveA += amountA;
        reserveB += amountB;
        lpShares[msg.sender] += sharesMinted;
        totalLPShares += sharesMinted;

        emit LiquidityAdded(msg.sender, amountA, amountB, sharesMinted);
        return sharesMinted;
    }

    function removeLiquidity(uint256 shares) external returns (uint256 amountA, uint256 amountB) {
        require(shares > 0, "shares must be > 0");
        require(shares <= lpShares[msg.sender], "insufficient shares");

        amountA = (shares * reserveA) / totalLPShares;
        amountB = (shares * reserveB) / totalLPShares;

        lpShares[msg.sender] -= shares;
        totalLPShares -= shares;
        reserveA -= amountA;
        reserveB -= amountB;

        IERC20Minimal(tokenA).transfer(msg.sender, amountA);
        IERC20Minimal(tokenB).transfer(msg.sender, amountB);

        emit LiquidityRemoved(msg.sender, amountA, amountB, shares);
        return (amountA, amountB);
    }

    // --- Phase 1: Submit encrypted orders ---
    function submitEncryptedOrder(bytes32 commitHash) external {
        require(currentPhase == BatchPhase.SUBMISSION, "not in submission phase");
        require(!pendingOrders[msg.sender].exists, "already submitted");

        pendingOrders[msg.sender] = EncryptedOrder({
            commitHash: commitHash,
            trader: msg.sender,
            exists: true
        });
        pendingTraders.push(msg.sender);

        emit OrderSubmitted(msg.sender, commitHash, batchId);
    }

    // --- Phase 2: Close submission window ---
    function closeSubmissionWindow() external {
        require(currentPhase == BatchPhase.SUBMISSION, "not in submission phase");
        require(pendingTraders.length > 0, "no pending orders");
        currentPhase = BatchPhase.CLOSED;
    }

    // --- Phase 3: Batch decrypt and execute all orders simultaneously ---
    // In a real threshold encryption system, the decryption key would only become
    // available when k-of-n key holders collaborate. Here the coordinator provides
    // the plaintext orders after the window closes.
    function batchDecryptAndExecute(
        address[] calldata traders,
        address[] calldata tokenIns,
        uint256[] calldata amountIns,
        uint256[] calldata amountOutMins,
        bytes32[] calldata secrets
    ) external {
        require(currentPhase == BatchPhase.CLOSED, "not in closed phase");
        require(traders.length == tokenIns.length, "length mismatch");
        require(traders.length == amountIns.length, "length mismatch");
        require(traders.length == amountOutMins.length, "length mismatch");
        require(traders.length == secrets.length, "length mismatch");

        // Clear previous results
        delete lastBatchResults;

        emit BatchDecrypted(batchId, traders.length);

        // Verify all hashes first (simulate decryption verification)
        for (uint256 i = 0; i < traders.length; i++) {
            bytes32 expectedHash = keccak256(abi.encodePacked(
                tokenIns[i], amountIns[i], amountOutMins[i], secrets[i]
            ));
            require(
                pendingOrders[traders[i]].exists &&
                pendingOrders[traders[i]].commitHash == expectedHash,
                "hash verification failed"
            );
        }

        // Execute all orders in the provided order (deterministic)
        for (uint256 i = 0; i < traders.length; i++) {
            bool success = _executeSwapInternal(
                traders[i], tokenIns[i], amountIns[i], amountOutMins[i]
            );

            // Record result regardless of success
            uint256 amountOut = 0;
            if (success && lastBatchResults.length > 0) {
                amountOut = lastBatchResults[lastBatchResults.length - 1].amountOut;
            }
            if (!success) {
                lastBatchResults.push(ExecutionResult({
                    trader: traders[i],
                    tokenIn: tokenIns[i],
                    amountIn: amountIns[i],
                    amountOut: 0,
                    success: false
                }));
            }
        }

        // Reset for next batch
        for (uint256 i = 0; i < pendingTraders.length; i++) {
            delete pendingOrders[pendingTraders[i]];
        }
        delete pendingTraders;
        currentPhase = BatchPhase.SUBMISSION;
        batchId++;
    }

    function _executeSwapInternal(
        address trader,
        address tokenIn,
        uint256 amountIn,
        uint256 amountOutMin
    ) internal returns (bool) {
        if (tokenIn != tokenA && tokenIn != tokenB) return false;
        if (amountIn == 0) return false;

        uint256 reserveIn;
        uint256 reserveOut;
        address tokenOut;

        if (tokenIn == tokenA) {
            reserveIn = reserveA;
            reserveOut = reserveB;
            tokenOut = tokenB;
        } else {
            reserveIn = reserveB;
            reserveOut = reserveA;
            tokenOut = tokenA;
        }

        uint256 amountInWithFee = amountIn * 997;
        uint256 amountOut = (reserveOut * amountInWithFee) / (reserveIn * 1000 + amountInWithFee);

        if (amountOut < amountOutMin || amountOut >= reserveOut) {
            lastBatchResults.push(ExecutionResult({
                trader: trader,
                tokenIn: tokenIn,
                amountIn: amountIn,
                amountOut: 0,
                success: false
            }));
            return false;
        }

        // Execute transfers
        IERC20Minimal(tokenIn).transferFrom(trader, address(this), amountIn);
        IERC20Minimal(tokenOut).transfer(trader, amountOut);

        if (tokenIn == tokenA) {
            reserveA += amountIn;
            reserveB -= amountOut;
        } else {
            reserveB += amountIn;
            reserveA -= amountOut;
        }

        lastBatchResults.push(ExecutionResult({
            trader: trader,
            tokenIn: tokenIn,
            amountIn: amountIn,
            amountOut: amountOut,
            success: true
        }));

        emit BatchOrderExecuted(batchId, trader, tokenIn, amountIn, amountOut);
        return true;
    }

    function getLastBatchResultsCount() external view returns (uint256) {
        return lastBatchResults.length;
    }

    function getPendingTraderCount() external view returns (uint256) {
        return pendingTraders.length;
    }

    function getReserves() external view returns (uint256, uint256) {
        return (reserveA, reserveB);
    }

    function getSpotPrice() external view returns (uint256) {
        require(reserveA > 0, "pool empty");
        return (reserveB * 1e18) / reserveA;
    }

    function quoteSwap(address tokenIn, uint256 amountIn) external view returns (uint256 amountOut) {
        require(tokenIn == tokenA || tokenIn == tokenB, "invalid token");
        require(amountIn > 0, "amountIn must be > 0");

        uint256 reserveIn;
        uint256 reserveOut;

        if (tokenIn == tokenA) {
            reserveIn = reserveA;
            reserveOut = reserveB;
        } else {
            reserveIn = reserveB;
            reserveOut = reserveA;
        }

        uint256 amountInWithFee = amountIn * 997;
        amountOut = (reserveOut * amountInWithFee) / (reserveIn * 1000 + amountInWithFee);
        return amountOut;
    }

    function computeCommitHash(
        address tokenIn,
        uint256 amountIn,
        uint256 amountOutMin,
        bytes32 secret
    ) external pure returns (bytes32) {
        return keccak256(abi.encodePacked(tokenIn, amountIn, amountOutMin, secret));
    }

    // Reset batch state (for simulator resets)
    function resetBatch() external {
        for (uint256 i = 0; i < pendingTraders.length; i++) {
            delete pendingOrders[pendingTraders[i]];
        }
        delete pendingTraders;
        delete lastBatchResults;
        currentPhase = BatchPhase.SUBMISSION;
    }
}
