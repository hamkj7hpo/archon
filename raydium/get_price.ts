import { Connection } from '@solana/web3.js';
import { Raydium } from '@raydium-io/raydium-sdk-v2';
import { readFileSync } from 'fs';
import path from 'path';// Config
const RPC_ENDPOINT = 'https://mainnet.helius-rpc.com/?api-key=479f2b3d-a5e4-4fa0-b7ac-163dc4b14133';
const TARGET_CONSTANTS_PATH = path.resolve(__dirname, '../target_constants.json');
const COMMITMENT = 'confirmed';async function getPrice(): Promise<void> {
  const connection = new Connection(RPC_ENDPOINT, COMMITMENT);  // Load constants
  const constants = JSON.parse(readFileSync(TARGET_CONSTANTS_PATH, 'utf-8'));
  const poolId = constants.target_token.pair_address;
  const ticker = constants.target_token.ticker;  // Initialize Raydium
  const raydium = await Raydium.load({ connection, cluster: 'mainnet' });  // Fetch pool info
  const poolData = await raydium.liquidity.getPoolInfoFromRpc({ poolId });
  const poolInfo = poolData.poolInfo;  // Extract price (tokens per SOL)
  const priceInSol = poolInfo.price;  // Output in JSON format for Python to parse
  const result = {
    ticker: ticker,
    priceInSol: priceInSol,
  };
  console.log(JSON.stringify(result));
}getPrice().catch(error => {
  console.error('Error:', error.message);
  process.exit(1);
});

