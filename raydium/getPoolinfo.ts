// getPoolInfo.ts

import { Connection, PublicKey } from "@solana/web3.js";
import {
  buildSimplePoolKeys,
  fetchMultiplePoolInfo,
  RAYDIUM_MAINNET_PROGRAM_ID,
} from "@raydium-io/raydium-sdk-v2";

// Replace with mainnet endpoint or devnet if you're testing
const connection = new Connection("https://api.mainnet-beta.solana.com", "confirmed");

async function main() {
  // This is the SOL/USDC AMM pool (Raydium)
  const AMM_ID = new PublicKey("6UeJ3FvXoHPzX79umK4yZr9h2cmxb3J9UAs4MFyxwbdP");

  const poolKeys = await buildSimplePoolKeys({
    connection,
    id: AMM_ID,
    programId: RAYDIUM_MAINNET_PROGRAM_ID.AmmV4, // or AmmV3 if applicable
  });

  const poolInfo = await fetchMultiplePoolInfo({
    connection,
    pools: [poolKeys],
  });

  console.log("Pool Info:", poolInfo);
}

main().catch(console.error);
