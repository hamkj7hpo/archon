import * as RaydiumSDK from '@raydium-io/raydium-sdk-v2';
import { Connection, PublicKey } from '@solana/web3.js';
import { getOrCreateAssociatedTokenAccount, TOKEN_PROGRAM_ID } from '@solana/spl-token';
import * as fs from 'fs';

// Set up Solana connection
const connection = new Connection('https://api.mainnet-beta.solana.com', 'confirmed');

// List of token addresses you want to fetch data for (e.g., Solana token mint addresses)
const TOKEN_MINT_ADDRESSES: string[] = [
  'So11111111111111111111111111111111111111112',  // Example: USDC mint address
  '4zCdfjWqa8MzFwY2YJzk3HKYc7VNKgaGRgEr98Q4BzFq'  // Example: Solana mint address
];

const OUTPUT_FILE = 'raydium_token_data.json';

// Function to fetch token price and liquidity data
async function fetchTokenData(tokenAddress: string) {
  try {
    const mintAddress = new PublicKey(tokenAddress);

    // Fetch associated token account data for the wallet (we assume it's the wallet's associated token account)
    const associatedTokenAccount = await getOrCreateAssociatedTokenAccount(
      connection,
      mintAddress,
      TOKEN_PROGRAM_ID,
      mintAddress // Assuming the token mint and wallet address are the same for this example
    );

    // Fetch the token price using Raydium SDK (ensure you are using the correct method for fetching token price)
    const priceData = await RaydiumSDK.toTokenPrice({
      token: associatedTokenAccount,  // Pass the associated token account
      numberPrice: 0  // Placeholder for the price; Raydium SDK should handle it
    });

    // You will need to find the correct method to fetch pool data
    const poolData = await fetchPoolData(tokenAddress);  // Use a custom function for pool data if needed

    // Return consolidated result
    return {
      tokenAddress,
      priceData,
      poolData
    };
  } catch (error) {
    console.error(`Error fetching data for token ${tokenAddress}:`, error);
    return null;
  }
}

// Placeholder function for pool data (replace with correct SDK method)
async function fetchPoolData(tokenAddress: string) {
  // Logic for fetching pool data here
  // This may depend on available methods in the SDK
  console.log(`Fetching pool data for token ${tokenAddress}...`);
  return {};  // Replace with actual data fetching logic
}

// Function to save the fetched data to a file
function saveDataToFile(data: any, filename: string): void {
  fs.writeFileSync(filename, JSON.stringify(data, null, 2));
  console.log(`Data saved to ${filename}`);
}

// Function to fetch and store token prices and liquidity data
async function fetchAndStoreTokenData() {
  const allData: any[] = [];

  for (const tokenAddress of TOKEN_MINT_ADDRESSES) {
    console.log(`Fetching data for token ${tokenAddress}...`);
    const tokenData = await fetchTokenData(tokenAddress);
    if (tokenData) {
      allData.push(tokenData);
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));  // Delay to avoid rate limits
  }

  if (allData.length > 0) {
    saveDataToFile(allData, OUTPUT_FILE);
  } else {
    console.log('No data to save.');
  }
}

// Run the script
fetchAndStoreTokenData();
