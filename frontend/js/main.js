// frontend/js/main.js
const queryInput = document.getElementById('query-input');
const submitButton = document.getElementById('submit-button');
const resultOutput = document.getElementById('result-output');
const errorOutput = document.getElementById('error-output');
const loadingIndicator = document.getElementById('loading-indicator');
const themeToggleButton = document.getElementById('theme-toggle-button'); // Get the toggle button
// const visualizeCheckbox = document.getElementById('visualize-checkbox');
// const chartOutput = document.getElementById('chart-output');

const API_URL = '/api/query';
const THEME_KEY = 'text2sql-theme'; // Key for localStorage

// --- Theme Handling ---
function applyTheme(theme) {
    if (theme === 'dark') {
        document.body.setAttribute('data-theme', 'dark');
    } else {
        document.body.removeAttribute('data-theme');
    }
}

function toggleTheme() {
    const currentTheme = document.body.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    applyTheme(newTheme);
    localStorage.setItem(THEME_KEY, newTheme); // Save preference
}

function loadTheme() {
    const savedTheme = localStorage.getItem(THEME_KEY);
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;

    if (savedTheme) {
        applyTheme(savedTheme);
    } else if (prefersDark) {
         // Default to system preference if no setting saved
        applyTheme('dark');
    } else {
        applyTheme('light'); // Default light
    }
}

// --- Event Listeners ---
submitButton.addEventListener('click', handleQuerySubmit);
queryInput.addEventListener('keypress', (event) => {
     if (event.key === 'Enter' && !event.shiftKey) {
          event.preventDefault();
          handleQuerySubmit();
     }
});
themeToggleButton.addEventListener('click', toggleTheme); // Add listener for theme toggle


// --- Functions (API handling remains the same) ---
async function handleQuerySubmit() {
    const queryText = queryInput.value.trim();
    // const visualize = visualizeCheckbox ? visualizeCheckbox.checked : false;

    if (!queryText) {
        showError("Please enter a query.");
        return;
    }

    setLoadingState(true);
    clearOutput();

    try {
        const response = await fetch(API_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify({
                query: queryText,
                // visualize: visualize
            })
        });

        const responseData = await response.json();

        if (!response.ok) {
            const errorMsg = responseData.detail || `HTTP error ${response.status}`;
            throw new Error(errorMsg);
        }

        if (responseData.sql_query) {
            resultOutput.textContent = responseData.sql_query;
        } else if (responseData.error) {
             showError(`Failed to generate SQL: ${responseData.error}`);
        } else {
             showError("Received an unexpected response format from the server.");
        }

        /* Phase 3 Viz Handling
        if (responseData.visualization) {
            try {
                const vizData = JSON.parse(responseData.visualization);
                Plotly.newPlot(chartOutput, vizData.data, vizData.layout, {responsive: true});
                chartOutput.style.display = 'block';
            } catch (e) {
                console.error("Error parsing or rendering visualization JSON:", e);
                showError("Received visualization data, but failed to render the chart.");
            }
        }
        if (responseData.execution_error) {
             showError(`SQL Execution Error: ${responseData.execution_error}`);
        }
        */

    } catch (error) {
        console.error("Error submitting query:", error);
        showError(`An error occurred: ${error.message}`);
    } finally {
        setLoadingState(false);
    }
}

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
    // chartOutput.innerHTML = '';
    // chartOutput.style.display = 'none';
}

function showError(message) {
    errorOutput.textContent = message;
    errorOutput.style.display = 'block';
}

// --- Initial setup ---
loadTheme(); // Load theme preference on page load
clearOutput();
