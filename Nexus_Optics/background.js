const WS_URL = "ws://127.0.0.1:8765";
let socket = null;
let reconnectDelay = 1000;
const MAX_RECONNECT_DELAY = 15000;
const queue = [];
const MAX_QUEUE_SIZE = 5;

function connectWebSocket() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
        return;
    }

    socket = new WebSocket(WS_URL);

    socket.onopen = () => {
        reconnectDelay = 1000; // Reset backoff
        // Flush queue
        while (queue.length > 0) {
            const msg = queue.shift();
            socket.send(JSON.stringify(msg));
        }
    };

    socket.onclose = () => {
        socket = null;
        setTimeout(connectWebSocket, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
    };

    socket.onerror = (err) => {
        if (socket) socket.close();
    };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message && message.type === "OPTICS_REPORT") {
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify(message));
        } else {
            queue.push(message);
            if (queue.length > MAX_QUEUE_SIZE) {
                queue.shift(); // Drop oldest message if queue is full
            }
            connectWebSocket(); // Ensure connection is attempting
        }
    }
});

// Initial connection
connectWebSocket();