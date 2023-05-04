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
        const data = JSON.stringify(Object.fromEntries(formData));

        // Get the current location and protocol
        const location = window.location;
        const protocol = location.protocol === "https:" ? "wss:" : "ws:";

        // Construct the WebSocket URL based on the current location and protocol
        const websocketURL = `${protocol}//${location.host}/ws`;

        // Send form data to server over websocket
        websocket = new WebSocket(websocketURL);
        websocket.onopen = () => {
            websocket.send(data);
        };

        websocket.onmessage = (event) => {
            const data = JSON.parse(event.data);

            if ('constructed_text' in data) {
                // Promise chain to ensure each new piece of text is only rendered after previous text finished rendering
                renderChain = renderChain.then(() => renderText(data));

                if (data.finished_constructing) {
                    renderChain.then(() => {
                        submitButton.disabled = false;
                    });
                };
            } 
            
            else if ('message' in data) {
                submitButton.disabled = false;
                document.getElementById('message').innerHTML = data.message;
            }
        };
    });
})

window.addEventListener('beforeunload', () => {
    // Send a beacon to the FastAPI app to stop constructing and reset words whenever page is refreshed
    navigator.sendBeacon('/reset_words');
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