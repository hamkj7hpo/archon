const { Connection, PublicKey, Keypair } = require('@solana/web3.js');
const fs = require('fs');

const RPC_ENDPOINT = 'https://api.mainnet-beta.solana.com';
const WALLET_KEYPAIR_PATH = '/home/joshua/solana/wallet.json';

function loadWallet() {
  try {
    const keypairData = JSON.parse(fs.readFileSync(WALLET_KEYPAIR_PATH, 'utf-8'));
    return Keypair.fromSecretKey(Uint8Array.from(keypairData));
  } catch (error) {
    console.error('Failed to load wallet:', error);
    process.exit(1);
  }
}

async function getWalletBalance() {
  const connection = new Connection(RPC_ENDPOINT, 'confirmed');
  const wallet = loadWallet();
  const publicKey = wallet.publicKey;

  try {
    const balanceLamports = await connection.getBalance(publicKey);
    const balanceSol = balanceLamports / 1_000_000_000; // Convert lamports to SOL
    console.log(balanceSol); // Output for Python to capture
    return balanceSol;
  } catch (error) {
    console.error('Failed to fetch balance:', error);
    process.exit(1);
  }
}

getWalletBalance().catch(error => {
  console.error('Error:', error);
  process.exit(1);
});
