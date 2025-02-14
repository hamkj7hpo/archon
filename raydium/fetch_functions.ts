import * as sdk from '@raydium-io/raydium-sdk-v2';

// Log all the available functions in the SDK
const sdkKeys = Object.keys(sdk);
console.log("All available functions in Raydium SDK:");
console.log(sdkKeys);

// Optionally filter for certain types of functions (e.g., 'price' or 'token')
const filteredKeys = sdkKeys.filter(key => key.toLowerCase().includes('price'));
console.log("\nFiltered functions related to 'price':");
console.log(filteredKeys);
