const queryInput = document.getElementById('query-input');
const submitButton = document.getElementById('submit-button');
const resultOutput = document.getElementById('result-output');
const errorOutput = document.getElementById('error-output');
const loadingIndicator = document.getElementById('loading-indicator');
const themeToggleButton = document.getElementById('theme-toggle-button');

const API_URL = '/api/query';
const THEME_KEY = 'text2sql-theme';
const SUN_ICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-sun"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`;
const MOON_ICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="feather feather-moon"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>`;

// --- Theme Handling ---
function applyTheme(theme) {
    if (theme === 'dark') {
        document.body.setAttribute('data-theme', 'dark');
        themeToggleButton.innerHTML = SUN_ICON_SVG;
        themeToggleButton.setAttribute('title', 'Switch to Light Mode');
    } else {
        document.body.removeAttribute('data-theme');
        themeToggleButton.innerHTML = MOON_ICON_SVG;
        themeToggleButton.setAttribute('title', 'Switch to Dark Mode');
    }
}
function toggleTheme() {
    const currentTheme = document.body.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    applyTheme(newTheme);
    localStorage.setItem(THEME_KEY, newTheme);
}
function loadTheme() {
    const savedTheme = localStorage.getItem(THEME_KEY);
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    let activeTheme = 'light';
    if (savedTheme) { activeTheme = savedTheme; }
    else if (prefersDark) { activeTheme = 'dark'; }
    applyTheme(activeTheme);
}

// --- Event Listeners ---
submitButton.addEventListener('click', handleQuerySubmit);
queryInput.addEventListener('keypress', (event) => {
     if (event.key === 'Enter' && !event.shiftKey) {
          event.preventDefault(); handleQuerySubmit();
     }
});
themeToggleButton.addEventListener('click', toggleTheme);

// --- handleQuerySubmit ---
async function handleQuerySubmit() {
    const queryText = queryInput.value.trim();
    if (!queryText) {
        showError("Please enter a query.");
        return;
    }

    setLoadingState(true);
    clearOutput();
    resultOutput.textContent = ''; // Clear previous results

    console.log("Sending query:", queryText); // Log query start

    try {
        const response = await fetch(API_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'text/plain' // Explicitly accept plain text
            },
            body: JSON.stringify({ query: queryText })
        });

        // --- Handle HTTP errors BEFORE trying to read body ---
        if (!response.ok) {
            let errorDetail = `Request failed with status ${response.status}`;
            // Try reading error body as text, as it might not be JSON
            try {
                const errorText = await response.text();
                console.error("Error response text:", errorText); // Log raw error text
                // Attempt to parse as JSON only if needed, but prioritize text
                 try {
                     const jsonError = JSON.parse(errorText);
                     errorDetail = jsonError.detail || errorText || errorDetail;
                 } catch(e) {
                     // If not JSON, use the plain text error
                     errorDetail = errorText || errorDetail;
                 }
            } catch (readError) {
                console.error("Could not read error response body:", readError);
            }
            // Throw the error *before* attempting to process stream
            throw new Error(errorDetail);
        }

        // --- Process the stream only if response.ok ---
        if (!response.body) {
             throw new Error("Response body is missing.");
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let streaming = true;
        console.log("Starting to read stream..."); // Log stream start

        while (streaming) {
            const { done, value } = await reader.read();
            if (done) {
                console.log("Stream finished (done is true)."); // Log stream end
                streaming = false;
                break;
            }
            const chunk = decoder.decode(value, { stream: true });
            console.log('Received chunk:', chunk); // **Log each received chunk**
            resultOutput.textContent += chunk; // Append text chunk
            resultOutput.scrollTop = resultOutput.scrollHeight; // Auto-scroll
        }

        if (resultOutput.textContent.length === 0) {
             console.log("Stream ended but no content received."); // Log empty case
             showError("Received an empty response from the server.");
        } else {
             console.log("Finished processing stream content."); // Log success
        }

    } catch (error) {
        // This catch block now handles fetch errors, network errors, or errors thrown above
        console.error("Fetch or stream processing error:", error);
        showError(`An error occurred: ${error.message}`);
    } finally {
        // Turn off loading indicator ONLY after stream finishes or catches an error
        setLoadingState(false);
        console.log("handleQuerySubmit finished."); // Log function end
    }
}



// --- Utility Functions ---
function setLoadingState(isLoading) {
    if (isLoading) {
        submitButton.disabled = true;
        loadingIndicator.style.display = 'block';
    } else {
        submitButton.disabled = false;
        loadingIndicator.style.display = 'none';
    }
}
function clearOutput() {
    resultOutput.textContent = '';
    errorOutput.textContent = '';
    errorOutput.style.display = 'none';
}
function showError(message) {
    errorOutput.textContent = message;
    errorOutput.style.display = 'block';
}

// --- Initial setup ---
loadTheme();
clearOutput();
