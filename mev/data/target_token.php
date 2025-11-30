<?php
$db_params = [
    'dbname' => 'archon_data',
    'user' => 'postgres',
    'password' => '!00$bMw$00!',
    'host' => 'localhost',
    'port' => '5432'
];

try {
    $conn = new PDO("pgsql:host={$db_params['host']};port={$db_params['port']};dbname={$db_params['dbname']}", $db_params['user'], $db_params['password']);
    $conn->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
} catch (PDOException $e) {
    die("Database connection failed: " . $e->getMessage());
}

$constants_file = '/home/joshua/archon/mev/data/target_constants.json';
$success_message = '';
$error_message = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $pair_address = $_POST['pair_address'] ?? '';
    $mint_address = $_POST['mint_address'] ?? '';
    $ticker = strtoupper($_POST['ticker'] ?? '');
    if ($pair_address && $mint_address && $ticker) {
        if (file_exists($constants_file)) {
            unlink($constants_file);
        }
        $data = ['target_token' => [
            'pair_address' => $pair_address,
            'mint_address' => $mint_address,
            'ticker' => $ticker
        ]];
        file_put_contents($constants_file, json_encode($data, JSON_PRETTY_PRINT));
        try {
            $stmt = $conn->prepare("UPDATE candlestick_data SET ticker = :ticker, token_mint = :mint_address WHERE token_pair = :pair_address");
            $stmt->execute(['ticker' => $ticker, 'mint_address' => $mint_address, 'pair_address' => $pair_address]);
            $success_message = "Token updated successfully!";
        } catch (PDOException $e) {
            $error_message = "Failed to update token: " . $e->getMessage();
        }
    } else {
        $error_message = "All fields are required!";
    }
}

$constants = json_decode(file_get_contents($constants_file), true) ?? ['target_token' => ['pair_address' => '', 'mint_address' => '', 'ticker' => '']];
$pair_address = $constants['target_token']['pair_address'];
$mint_address = $constants['target_token']['mint_address'];
$ticker = strtoupper($constants['target_token']['ticker']);

// Fetch recent trades (last 5 minutes)
$interval = 15; // 15-second columns
$time_limit = date('Y-m-d H:i:s', time() - 300); // Last 5 minutes
$trades = [];
$columns = [];
$trade_counts = ['🟢' => 0, '🔴' => 0, '⚪' => 0];
try {
    $stmt = $conn->prepare(
        "SELECT 
            timestamp,
            transaction_type,
            transaction_emoji,
            open AS amount
        FROM candlestick_data 
        WHERE token_pair = :pair_address AND timestamp >= :time_limit
        ORDER BY timestamp ASC"
    );
    $stmt->execute(['pair_address' => $pair_address, 'time_limit' => $time_limit]);
    $trades = $stmt->fetchAll(PDO::FETCH_ASSOC);

    // Group trades into 15-second columns
    foreach ($trades as $trade) {
        $timestamp = new DateTime($trade['timestamp']);
        $seconds = $timestamp->getTimestamp();
        $column_start = $seconds - ($seconds % $interval);
        $column_key = date('Y-m-d H:i:s', $column_start);
        
        if (!isset($columns[$column_key])) {
            $columns[$column_key] = ['buys' => [], 'sells' => [], 'holds' => []];
        }
        
        $emoji = $trade['transaction_emoji'];
        $amount = (float)$trade['amount'];
        if ($trade['transaction_type'] === 'buy') {
            $columns[$column_key]['buys'][] = ['emoji' => $emoji, 'amount' => $amount];
        } elseif ($trade['transaction_type'] === 'sell') {
            $columns[$column_key]['sells'][] = ['emoji' => $emoji, 'amount' => $amount];
        } else {
            $columns[$column_key]['holds'][] = ['emoji' => $emoji, 'amount' => $amount];
        }
        $trade_counts[$emoji]++;
    }
} catch (PDOException $e) {
    $error_message = "Failed to fetch trades: " . $e->getMessage();
}
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Target Token Emoji Chart - Solana Surge</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH" crossorigin="anonymous">
    <style>
        :root {
            --surge-green: #00FFA3;
            --ocean-blue: #03E1FF;
            --purple-dino: #DC1FFF;
            --black: #000000;
        }
        body {
            background: linear-gradient(135deg, var(--ocean-blue), var(--black));
            color: var(--surge-green);
            font-family: 'Roboto', sans-serif;
            min-height: 100vh;
        }
        .container {
            background: rgba(0, 0, 0, 0.85);
            border-radius: 15px;
            padding: 20px;
            box-shadow: 0 0 20px rgba(0, 255, 163, 0.5);
            margin-top: 20px;
        }
        h1, h2 {
            color: var(--purple-dino);
            text-shadow: 0 0 10px var(--surge-green);
        }
        .form-control {
            background-color: var(--black);
            border-color: var(--surge-green);
            color: var(--ocean-blue);
        }
        .form-control:focus {
            background-color: var(--black);
            border-color: var(--purple-dino);
            color: var(--ocean-blue);
            box-shadow: 0 0 5px var(--purple-dino);
        }
        .btn-surge {
            background-color: var(--surge-green);
            border-color: var(--surge-green);
            color: var(--black);
            transition: all 0.3s ease;
        }
        .btn-surge:hover {
            background-color: var(--purple-dino);
            border-color: var(--purple-dino);
            color: var(--black);
            box-shadow: 0 0 15px var(--purple-dino);
        }
        .alert-surge {
            background-color: var(--surge-green);
            color: var(--black);
            border-color: var(--surge-green);
        }
        .alert-danger {
            background-color: #ff4444;
            color: var(--black);
            border-color: #ff4444;
        }
        .emoji-chart {
            background: var(--black);
            border-radius: 10px;
            padding: 15px;
            overflow-x: auto;
            white-space: nowrap;
            font-size: 1.5em;
        }
        .column {
            display: inline-block;
            margin-right: 20px;
            text-align: center;
        }
        .column-timestamp {
            color: var(--ocean-blue);
            font-size: 0.8em;
            margin-bottom: 5px;
        }
        .trade-counts {
            margin-top: 20px;
            font-size: 1.2em;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1 class="text-center mb-4">Solana Target Token Emoji Chart</h1>

        <?php if ($success_message): ?>
            <div class="alert alert-surge alert-dismissible fade show" role="alert">
                <?php echo htmlspecialchars($success_message); ?>
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        <?php endif; ?>

        <?php if ($error_message): ?>
            <div class="alert alert-danger alert-dismissible fade show" role="alert">
                <?php echo htmlspecialchars($error_message); ?>
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        <?php endif; ?>

        <div class="row">
            <div class="col-md-6 mx-auto">
                <h2 class="mb-3">Set Target Token</h2>
                <form method="POST">
                    <div class="mb-3">
                        <label for="pair_address" class="form-label">Pair Address</label>
                        <input type="text" class="form-control" id="pair_address" name="pair_address" value="<?php echo htmlspecialchars($constants['target_token']['pair_address']); ?>" required>
                    </div>
                    <div class="mb-3">
                        <label for="mint_address" class="form-label">Mint Address</label>
                        <input type="text" class="form-control" id="mint_address" name="mint_address" value="<?php echo htmlspecialchars($constants['target_token']['mint_address']); ?>" required>
                    </div>
                    <div class="mb-3">
                        <label for="ticker" class="form-label">Ticker</label>
                        <input type="text" class="form-control" id="ticker" name="ticker" value="<?php echo htmlspecialchars($constants['target_token']['ticker']); ?>" required>
                    </div>
                    <button type="submit" class="btn btn-surge w-100">Update Token</button>
                </form>
            </div>
        </div>

        <h2 class="mt-5 text-center">Emoji Trade Chart for <?php echo htmlspecialchars($ticker); ?></h2>
        <div class="emoji-chart">
            <?php if (empty($columns)): ?>
                <p>No trades in the last 5 minutes.</p>
            <?php else: ?>
                <?php foreach ($columns as $timestamp => $column): ?>
                    <div class="column">
                        <div class="column-timestamp"><?php echo htmlspecialchars($timestamp); ?></div>
                        <?php
                        // Green buys on top
                        foreach ($column['buys'] as $trade) {
                            echo '<div title="Buy: ' . htmlspecialchars($trade['amount']) . '">' . htmlspecialchars($trade['emoji']) . '</div>';
                        }
                        // Holds in the middle
                        foreach ($column['holds'] as $trade) {
                            echo '<div title="Hold: ' . htmlspecialchars($trade['amount']) . '">' . htmlspecialchars($trade['emoji']) . '</div>';
                        }
                        // Red sells on the bottom
                        foreach ($column['sells'] as $trade) {
                            echo '<div title="Sell: ' . htmlspecialchars($trade['amount']) . '">' . htmlspecialchars($trade['emoji']) . '</div>';
                        }
                        ?>
                    </div>
                <?php endforeach; ?>
            <?php endif; ?>
        </div>

        <div class="trade-counts text-center">
            <p>Trade Totals: 
                🟢 <?php echo $trade_counts['🟢']; ?> | 
                🔴 <?php echo $trade_counts['🔴']; ?> | 
                ⚪ <?php echo $trade_counts['⚪']; ?>
            </p>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js" integrity="sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz" crossorigin="anonymous"></script>
    <script>
        setInterval(() => {
            fetch(window.location.href, { method: 'GET' })
                .then(response => response.text())
                .then(html => {
                    const parser = new DOMParser();
                    const doc = parser.parseFromString(html, 'text/html');
                    const newChart = doc.querySelector('.emoji-chart').innerHTML;
                    const newCounts = doc.querySelector('.trade-counts').innerHTML;
                    document.querySelector('.emoji-chart').innerHTML = newChart;
                    document.querySelector('.trade-counts').innerHTML = newCounts;
                })
                .catch(error => console.error('Error updating chart:', error));
        }, 5000);
    </script>
</body>
</html>
