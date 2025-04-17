// --- DOM Elements ---
const queryInput = document.getElementById('query-input');
const submitButton = document.getElementById('submit-button');
const sqlOutput = document.getElementById('sql-output'); // For raw SQL
const resultOutput = document.getElementById('result-output'); // For rendered result
const errorOutput = document.getElementById('error-output');
const loadingIndicator = document.getElementById('loading-indicator');
const resultsSection = document.getElementById('results-section'); // Container for results

const uploadForm = document.getElementById('upload-form');
const fileInput = document.getElementById('file-input');
const uploadButton = document.getElementById('upload-button');
const uploadStatus = document.getElementById('upload-status');

const themeToggleButton = document.getElementById('theme-toggle-button');

// --- API URLs ---
const QUERY_API_URL = '/api/query';
const UPLOAD_API_URL = '/api/upload_doc';

// --- Constants ---
const THEME_KEY = 'text2sql-theme';
const SUN_ICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`;
const MOON_ICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>`;

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
    let activeTheme = savedTheme || (prefersDark ? 'dark' : 'light');
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
uploadForm.addEventListener('submit', handleUploadSubmit);


// --- Query Submission Handler ---
async function handleQuerySubmit() {
    const queryText = queryInput.value.trim();
    if (!queryText) {
        showError("Please enter a query.");
        return;
    }

    setLoadingState(true);
    clearOutput(); // Clears previous results and errors

    console.log("Sending query:", queryText);

    try {
        const response = await fetch(QUERY_API_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json' // Expect JSON response
            },
            body: JSON.stringify({ query: queryText })
        });

        const data = await response.json(); // Parse the JSON response

        if (!response.ok) {
            // Use error message from backend response if available
            throw new Error(data.detail || data.error || `Request failed with status ${response.status}`);
        }

        console.log("Received response:", data);

        // Handle potential errors returned in a 2xx response
        if (data.error) {
            showError(data.error);
            // Still display SQL if it was generated before the error (e.g., execution error)
             if (data.sql_query) {
                 // Clean SQL even if there's an execution error later
                 const cleanedSql = cleanSqlString(data.sql_query); // Call cleaning function
                 sqlOutput.textContent = cleanedSql;
                 resultsSection.style.display = 'block'; // Show section even with error if SQL exists
             }
            return; // Stop further processing
        }

        // Display SQL Query
        if (data.sql_query) {
            // Clean the SQL string before displaying
            const cleanedSql = cleanSqlString(data.sql_query); // Call cleaning function
            sqlOutput.textContent = cleanedSql;
        } else {
            sqlOutput.textContent = "-- No SQL query generated --";
        }

        // Display Result (Rendered Markdown or Plain Text)
        if (data.result !== null && data.result !== undefined) {
            if (typeof data.result === 'string') {
                 // Use marked to parse the result string into HTML
                 // Note: No sanitization is applied here by default with marked.
                 // If the source of 'data.result' wasn't fully trusted, you'd use DOMPurify:
                 // resultOutput.innerHTML = DOMPurify.sanitize(marked.parse(data.result));
                 resultOutput.innerHTML = marked.parse(data.result);
            } else {
                 // Handle non-string results (e.g., numbers, JSON objects if API changes)
                 resultOutput.textContent = JSON.stringify(data.result, null, 2);
            }
        } else {
            resultOutput.textContent = "-- Query executed successfully, but returned no data. --";
        }

        resultsSection.style.display = 'block'; // Show the results section

    } catch (error) {
        console.error("Query fetch or processing error:", error);
        showError(`An error occurred: ${error.message}`);
        resultsSection.style.display = 'none'; // Hide results section on fetch error
    } finally {
        setLoadingState(false);
        console.log("handleQuerySubmit finished.");
    }
}

// --- Document Upload Handler ---
async function handleUploadSubmit(event) {
    event.preventDefault();

    const files = fileInput.files;
    if (!files || files.length === 0) {
        showUploadStatus("Please select one or more files.", 'error');
        return;
    }

    setUploadLoadingState(true);
    let successfulUploads = 0;
    let failedUploads = 0;
    const totalFiles = files.length;
    let cumulativeChunks = 0;

    showUploadStatus(`Starting upload of ${totalFiles} file(s)...`, 'info'); // Use 'info' for neutral

    for (let i = 0; i < totalFiles; i++) {
        const file = files[i];
        const currentFileNum = i + 1;

        showUploadStatus(`Uploading file ${currentFileNum}/${totalFiles}: ${file.name}...`, 'info');

        const allowedExtensions = ['.pdf', '.docx', '.txt', '.md'];
        const fileExtension = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
        // Basic client-side check (server validation is primary)
        if (!allowedExtensions.includes(fileExtension)) {
             console.warn(`Skipping file ${file.name} due to invalid extension: ${fileExtension}`);
             // Don't show a persistent error, maybe just log or a temporary notice
             // showUploadStatus(`Skipped file ${currentFileNum}/${totalFiles}: ${file.name} (invalid type).`, 'error');
             failedUploads++;
             continue;
        }

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch(UPLOAD_API_URL, {
                method: 'POST',
                body: formData,
                headers: { 'Accept': 'application/json' }
            });

            const result = await response.json();

            if (!response.ok) {
                throw new Error(`(${file.name}) ${result.detail || `Upload failed status ${response.status}`}`);
            }

            console.log(`Successfully uploaded ${file.name}. Chunks: ${result.chunks_added}`);
            successfulUploads++;
            cumulativeChunks += result.chunks_added;
            // Can update status less frequently if needed
            // showUploadStatus(`Uploaded file ${currentFileNum}/${totalFiles}: ${file.name} (${result.chunks_added} chunks).`, 'info');

        } catch (error) {
            console.error(`Upload error for file ${file.name}:`, error);
            // Show error for the specific file, but continue loop
            showUploadStatus(`Error uploading file ${currentFileNum}/${totalFiles}: ${file.name} - ${error.message}`, 'error');
            failedUploads++;
        }
    }

    // Final status update
    let finalMessage = `Finished uploads. ${successfulUploads}/${totalFiles} successful (${cumulativeChunks} total chunks added).`;
    let finalStatusType = 'success';
    if (failedUploads > 0) {
        finalMessage += ` ${failedUploads} failed.`;
        finalStatusType = successfulUploads > 0 ? 'warning' : 'error'; // Show warning if partial success
    }
    showUploadStatus(finalMessage, finalStatusType);
    fileInput.value = ''; // Clear the file input
    setUploadLoadingState(false);
}


// --- Utility Functions ---
function setLoadingState(isLoading) {
    submitButton.disabled = isLoading;
    if (isLoading) {
        loadingIndicator.style.display = 'flex'; // Use flex to align spinner and text
    } else {
        loadingIndicator.style.display = 'none';
    }
}

function setUploadLoadingState(isLoading) {
    uploadButton.disabled = isLoading;
    fileInput.disabled = isLoading;
}

function showUploadStatus(message, type = 'info') { // type: 'info', 'success', 'error', 'warning'
    uploadStatus.textContent = message;
    uploadStatus.className = 'status-message'; // Reset classes
    if (type === 'success') {
        uploadStatus.classList.add('success');
    } else if (type === 'error') {
        uploadStatus.classList.add('error');
    } else if (type === 'warning'){
         uploadStatus.classList.add('warning'); // Optional: Add CSS for warning state if needed
    }
    // 'info' uses default styling
    uploadStatus.style.display = 'block';
}


function clearOutput() {
    sqlOutput.textContent = '';
    resultOutput.innerHTML = ''; // Clear innerHTML for the div
    errorOutput.textContent = '';
    errorOutput.style.display = 'none';
    resultsSection.style.display = 'none'; // Hide the results section
    // Keep upload status visible unless explicitly cleared
}

function showError(message) {
    errorOutput.textContent = message;
    errorOutput.style.display = 'block';
     resultsSection.style.display = 'none'; // Hide results section when showing a query error
}

function cleanSqlString(rawSql) {
    if (!rawSql) return "";
    // Remove leading ```sql, optional language specifier, and trailing ```
    let cleaned = rawSql.trim();
    cleaned = cleaned.replace(/^```(?:sql)?\s*/i, ''); // Remove ```sql or ``` at the start (case-insensitive)
    cleaned = cleaned.replace(/```\s*$/, '');    // Remove ``` at the end
    return cleaned.trim(); // Trim final whitespace
}

// --- Initial setup ---
loadTheme();
clearOutput(); // Clear query output/errors on load
uploadStatus.style.display = 'none'; // Hide upload status initially