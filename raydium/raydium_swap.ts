import { Raydium, TxVersion } from '@raydium-io/raydium-sdk-v2';
import { Connection, Keypair, LAMPORTS_PER_SOL, PublicKey } from '@solana/web3.js';
import BN from 'bn.js';
import fs from 'fs';
import path from 'path';

// Config
const RPC_ENDPOINT = 'https://mainnet.helius-rpc.com/?api-key=479f2b3d-a5e4-4fa0-b7ac-163dc4b14133';
const TARGET_CONSTANTS_PATH = path.resolve(__dirname, '../target_constants.json');
const COMMITMENT = 'confirmed';
const MIN_MICRO_BUY = 0.0015;

interface TargetConstants {
    target_token: {
        pair_address: string;
        mint_address: string;
        ticker: string;
    };
}

function loadConstants(): TargetConstants {
    try {
        const data = fs.readFileSync(TARGET_CONSTANTS_PATH, 'utf8');
        const constants = JSON.parse(data) as TargetConstants;
        if (!constants.target_token?.pair_address || !constants.target_token?.mint_address || !constants.target_token?.ticker) {
            throw new Error('Missing required fields in target_constants.json');
        }
        return constants;
    } catch (error) {
        console.error(`Failed to load constants from ${TARGET_CONSTANTS_PATH}: ${error}`);
        throw error;
    }
}

// Load constants
const constants = loadConstants();
const POOL_ID = constants.target_token.pair_address;
const TARGET_MINT = constants.target_token.mint_address;
const TICKER = constants.target_token.ticker;

// Utility functions
async function getConnection(): Promise<Connection> {
    return new Connection(RPC_ENDPOINT, COMMITMENT);
}

function loadWallet(): Keypair {
    const secretKey = Buffer.from(JSON.parse(fs.readFileSync('wallet.json', 'utf8')));
    return Keypair.fromSecretKey(secretKey);
}

async function getTokenBalance(connection: Connection, wallet: Keypair, mint: string): Promise<number> {
    const mintPubkey = new PublicKey(mint);
    const tokenAccounts = await connection.getTokenAccountsByOwner(wallet.publicKey, { mint: mintPubkey });
    if (tokenAccounts.value.length === 0) return 0;
    const accountInfo = await connection.getTokenAccountBalance(tokenAccounts.value[0].pubkey);
    return accountInfo.value.uiAmount || 0;
}

async function retryOnError<T>(fn: () => Promise<T>, retries = 3): Promise<T> {
    for (let i = 0; i < retries; i++) {
        try {
            return await fn();
        } catch (e) {
            if (i === retries - 1) throw e;
            await new Promise(res => setTimeout(res, 2000));
        }
    }
    throw new Error('Retry limit reached');
}

let raydium: Raydium | undefined;

async function executeSwap(amountIn: number, isBuy: boolean, slippage: number): Promise<string> {
    process.stdout.write(`Starting executeSwap: amountIn=${amountIn}, isBuy=${isBuy}, slippage=${slippage}, Ticker=${TICKER}\n`);
    const connection = await getConnection();
    const wallet = loadWallet();
    process.stdout.write(`Wallet public key: ${wallet.publicKey.toBase58()}\n`);

    const decimalsIn = isBuy ? 9 : 6; // SOL: 9, JELLY: 6
    const decimalsOut = isBuy ? 6 : 9;
    const amountInScaled = amountIn * Math.pow(10, decimalsIn);
    process.stdout.write(`Scaled amount: ${amountInScaled}\n`);
    const amountInLamports = new BN(Math.floor(amountInScaled));
    process.stdout.write(`Amount in lamports: ${amountInLamports.toString()}\n`);

    if (!raydium) {
        process.stdout.write('Loading Raydium SDK...\n');
        raydium = await Raydium.load({ connection, owner: wallet, cluster: 'mainnet' });
    }

    process.stdout.write('Fetching pool info...\n');
    const poolData = await raydium.liquidity.getPoolInfoFromRpc({ poolId: POOL_ID });
    const poolInfo = poolData.poolInfo;
    process.stdout.write(`Pool info: ${JSON.stringify(poolInfo)}\n`);

    const inputMint = isBuy ? 'So11111111111111111111111111111111111111112' : TARGET_MINT;

    // Balance check
    if (!isBuy) {
        const tokenBalance = await getTokenBalance(connection, wallet, inputMint);
        process.stdout.write(`Current ${TICKER} balance: ${tokenBalance}\n`);
        if (tokenBalance < amountIn) {
            throw new Error(`Insufficient ${TICKER} balance: ${tokenBalance} < ${amountIn}`);
        }
    } else {
        const solBalance = (await connection.getBalance(wallet.publicKey)) / LAMPORTS_PER_SOL;
        process.stdout.write(`Current SOL balance: ${solBalance}\n`);
        if (solBalance < amountIn) {
            throw new Error(`Insufficient SOL balance: ${solBalance} < ${amountIn}`);
        }
    }

    process.stdout.write('Preparing swap...\n');
    // Price in JELLY/SOL for consistency with Python script
    const poolPrice = isBuy ? poolInfo.price : (1 / poolInfo.price);
    const expectedOut = amountIn * poolPrice;
    const minAmountOutRaw = expectedOut * (1 - slippage);
    const minAmountOutLamports = minAmountOutRaw > 0 ? Math.floor(minAmountOutRaw * Math.pow(10, decimalsOut)) : 0;
    process.stdout.write(`Pre-BN: minAmountOutRaw=${minAmountOutRaw}, minAmountOutLamports=${minAmountOutLamports}\n`);
    const minAmountOut = new BN(minAmountOutLamports);
    process.stdout.write(`Pool price: ${poolPrice}, Expected out: ${expectedOut}, Min out: ${minAmountOut.toString()}\n`);

    const { execute, transaction } = await raydium.liquidity.swap({
        poolInfo,
        inputMint,
        amountIn: amountInLamports,
        amountOut: minAmountOut,
        fixedSide: 'in',
        txVersion: TxVersion.LEGACY,
    });

    const { blockhash, lastValidBlockHeight } = await connection.getLatestBlockhash('recent');
    transaction.recentBlockhash = blockhash;
    transaction.sign(wallet);

    process.stdout.write('Executing swap...\n');
    process.stdout.write(`simulate tx string: [\n  '${transaction.serialize({ requireAllSignatures: false }).toString('base64')}'\n]\n`);

    const txId = await retryOnError(async () => {
        const txSig = await connection.sendRawTransaction(transaction.serialize(), {
            skipPreflight: false,
            preflightCommitment: COMMITMENT,
        });
        await connection.confirmTransaction({
            signature: txSig,
            blockhash,
            lastValidBlockHeight,
        });
        return txSig;
    });

    process.stdout.write(`Transaction ID: ${txId}\n`);
    return txId;
}

if (process.argv[2] === 'swap') {
    const amount = parseFloat(process.argv[3]);
    const isBuy = parseInt(process.argv[4]) === 1;
    const tokenMint = process.argv[5];
    const slippage = process.argv[6] ? parseFloat(process.argv[6]) : 0.005;
    console.log(`Received arguments: amount=${amount}, isBuy=${isBuy}, tokenMint=${tokenMint}, slippage=${slippage}, Ticker=${TICKER}`);
    // Validate tokenMint matches TARGET_MINT
    if (tokenMint !== TARGET_MINT) {
        console.error(`Token mint mismatch: expected ${TARGET_MINT}, got ${tokenMint}`);
        process.exit(1);
    }
    executeSwap(amount, isBuy, slippage)
        .then(txId => {
            console.log(`Swap successful with TXID: ${txId}`);
            process.exit(0);
        })
        .catch(error => {
            console.error('Swap failed:', error);
            process.exit(1);
        });
}
