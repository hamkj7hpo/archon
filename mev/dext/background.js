browser.runtime.onMessage.addListener((message) => {
  if (message.trades) {
    fetch('http://localhost:8000/trades', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(message.trades)
    })
    .then(response => console.log('Trades sent:', response))
    .catch(error => console.error('Error sending trades:', error));
  }
});
