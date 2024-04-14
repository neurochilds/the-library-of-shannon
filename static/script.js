let lastRenderedText = '';
let stopRequested = false;
let renderChain = Promise.resolve();
let websocket = '';

document.addEventListener("DOMContentLoaded", function() {
    const form = document.getElementById("parameters")
    form.addEventListener("submit", function(event){
        event.preventDefault();

        // Disable the submit button until text construction finished
        const submitButton = document.getElementById('submitBtn');
        submitButton.disabled = true;

        // Delete any existing text and reset variables
        resetInnerHTML('text', 'selected_order', 'selected_book', 'message')
        lastRenderedText = ''
        stopRequested = false;

        // Get form data
        const formData = new FormData(event.target);
        const formString = JSON.stringify(Object.fromEntries(formData));

        // Get the current location and protocol
        const location = window.location;
        const protocol = location.protocol === "https:" ? "wss:" : "ws:";

        // Close existing socket if one exists
        if (websocket && websocket.readyState === WebSocket.OPEN) {
            websocket.close();  
        }

        // Construct the WebSocket URL based on the current location and protocol
        const websocketURL = `${protocol}//${location.host}/ws`;

        websocket = new WebSocket(websocketURL);
        websocket.onopen = () => {
            console.log('WebSocket opened, sending form data');
            websocket.send(formString);
        };
        websocket.onmessage = handleWebSocketMessage;
        websocket.onclose = () => console.log('WebSocket closed');

        });
});

function handleWebSocketMessage(event) {
    const data = JSON.parse(event.data);
    if (data.session_id) {
        sessionStorage.setItem('session_id', data.session_id);
    }

    else if ('constructed_text' in data) {
        // Promise chain to ensure each new piece of text is only rendered after previous text finished rendering
        renderChain = renderChain.then(() => renderText(data));

        if (data.finished_constructing) {
            renderChain.then(() => {
                document.getElementById('submitBtn').disabled = false;
            });
        };
    } 
    
    else if ('message' in data) {
        document.getElementById('submitBtn').disabled = false;
        document.getElementById('message').innerHTML = data.message;
    }

}

window.addEventListener('beforeunload', () => {
    // Close the WebSocket when page refreshed
    if (websocket && websocket.readyState === WebSocket.OPEN) {
        websocket.close();  
    }

    // Send a beacon to the FastAPI app to stop constructing and reset words whenever page is refreshed
    const sessionID = sessionStorage.getItem('session_id');
    if(sessionID) {
        const data = new FormData();
        data.append('session_id', sessionStorage.getItem('session_id'));
        navigator.sendBeacon('/reset_words', data);
    }
});            

function resetInnerHTML(...elementIds) {
    elementIds.forEach(id => {
        document.getElementById(id).innerHTML = '';
    });
}

async function renderText(data) {
    const currentText = data.constructed_text;

    document.getElementById('selected_book').innerHTML = 'Book ' + data.book
    document.getElementById('selected_order').innerHTML = 'Order ' + data.order

    if (currentText.length > lastRenderedText.length) {
        await renderNewWords(lastRenderedText, currentText);
        lastRenderedText = currentText;
    }
}

async function renderNewWords(oldText, newText) {
        const newWords = newText.slice(oldText.length);
        await typeText(newWords);
}

async function typeText(text) {
    // Render the text letter by letter
    const textElement = document.getElementById('text');
    for (const char of text) {
        if (stopRequested) return;
        if (char == '<') {
            textElement.innerHTML += '<br>'
        } else {
            textElement.innerHTML += char;
        }
        await delay(20) // Control typing speed
    }
}

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms))
}

async function stopConstructingWords() {
    stopRequested = true;
    await websocket.send(JSON.stringify({"stop": true}));
    document.getElementById('submitBtn').disabled = false;
}