// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IERC20Minimal {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function transfer(address to, uint256 amount) external returns (bool);
}

contract CommitRevealDEX {
    address public tokenA;
    address public tokenB;
    uint256 public reserveA;
    uint256 public reserveB;

    mapping(address => uint256) public lpShares;
    uint256 public totalLPShares;

    // Commit-reveal state
    struct Commitment {
        bytes32 commitHash;
        uint256 commitBlock;
        bool revealed;
        bool exists;
    }

    mapping(address => Commitment) public commitments;

    event LiquidityAdded(address indexed provider, uint256 amountA, uint256 amountB, uint256 sharesMinted);
    event LiquidityRemoved(address indexed provider, uint256 amountA, uint256 amountB, uint256 sharesBurned);
    event Swap(address indexed trader, address tokenIn, uint256 amountIn, uint256 amountOut);
    event SwapCommitted(address indexed trader, bytes32 commitHash, uint256 commitBlock);
    event SwapRevealed(address indexed trader, address tokenIn, uint256 amountIn, uint256 amountOut);

    constructor(address _tokenA, address _tokenB) {
        tokenA = _tokenA;
        tokenB = _tokenB;
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

    // --- Regular swap (same as SimpleDEX, used for attacks / comparison) ---
    function swap(address tokenIn, uint256 amountIn, uint256 amountOutMin) external returns (uint256 amountOut) {
        require(tokenIn == tokenA || tokenIn == tokenB, "invalid token");
        require(amountIn > 0, "amountIn must be > 0");

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
        amountOut = (reserveOut * amountInWithFee) / (reserveIn * 1000 + amountInWithFee);

        require(amountOut >= amountOutMin, "slippage");
        require(amountOut < reserveOut, "insufficient reserve");

        IERC20Minimal(tokenIn).transferFrom(msg.sender, address(this), amountIn);
        IERC20Minimal(tokenOut).transfer(msg.sender, amountOut);

        if (tokenIn == tokenA) {
            reserveA += amountIn;
            reserveB -= amountOut;
        } else {
            reserveB += amountIn;
            reserveA -= amountOut;
        }

        emit Swap(msg.sender, tokenIn, amountIn, amountOut);
        return amountOut;
    }

    // --- Commit phase ---
    function commitSwap(bytes32 commitHash) external {
        // Allow overwriting previous uncommitted commit
        commitments[msg.sender] = Commitment({
            commitHash: commitHash,
            commitBlock: block.number,
            revealed: false,
            exists: true
        });

        emit SwapCommitted(msg.sender, commitHash, block.number);
    }

    // --- Reveal phase ---
    function revealSwap(
        address tokenIn,
        uint256 amountIn,
        uint256 amountOutMin,
        bytes32 secret
    ) external returns (uint256 amountOut) {
        Commitment storage c = commitments[msg.sender];
        require(c.exists, "no commitment found");
        require(!c.revealed, "already revealed");

        // Verify hash matches
        bytes32 expectedHash = keccak256(abi.encodePacked(tokenIn, amountIn, amountOutMin, secret));
        require(expectedHash == c.commitHash, "hash mismatch");

        // Must reveal in a later block than commit
        require(block.number > c.commitBlock, "reveal too early");

        c.revealed = true;

        // Execute the swap
        require(tokenIn == tokenA || tokenIn == tokenB, "invalid token");
        require(amountIn > 0, "amountIn must be > 0");

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
        amountOut = (reserveOut * amountInWithFee) / (reserveIn * 1000 + amountInWithFee);

        require(amountOut >= amountOutMin, "slippage");
        require(amountOut < reserveOut, "insufficient reserve");

        IERC20Minimal(tokenIn).transferFrom(msg.sender, address(this), amountIn);
        IERC20Minimal(tokenOut).transfer(msg.sender, amountOut);

        if (tokenIn == tokenA) {
            reserveA += amountIn;
            reserveB -= amountOut;
        } else {
            reserveB += amountIn;
            reserveA -= amountOut;
        }

        emit SwapRevealed(msg.sender, tokenIn, amountIn, amountOut);
        return amountOut;
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

    // Helper to compute commit hash off-chain (view)
    function computeCommitHash(
        address tokenIn,
        uint256 amountIn,
        uint256 amountOutMin,
        bytes32 secret
    ) external pure returns (bytes32) {
        return keccak256(abi.encodePacked(tokenIn, amountIn, amountOutMin, secret));
    }
}
