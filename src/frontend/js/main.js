// --- DOM Elements ---
const queryInput = document.getElementById('query-input');
const submitButton = document.getElementById('submit-button');
// Get the CODE element for SQL output
const sqlOutputCode = document.getElementById('sql-output-code');
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
    // Potentially re-highlight after theme change if colors depend heavily on it
    // and CSS overrides aren't sufficient (usually not needed if CSS vars are used well)
    if (sqlOutputCode.textContent) {
        Prism.highlightElement(sqlOutputCode);
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
/**
 * Submits the user's query to the backend and streams SQL/result chunks to the UI in real time.
 * Handles plain text streaming with section markers: --SQL-END--, --RESULT--, --ERROR--
 */
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
                'Accept': 'text/plain'
            },
            body: JSON.stringify({ query: queryText })
        });

        if (!response.ok) {
            let errMsg = `Request failed with status ${response.status}`;
            try {
                const errData = await response.json();
                errMsg = errData.detail || errData.error || errMsg;
            } catch { /* ignore */ }
            throw new Error(errMsg);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let sqlBuffer = '';
        let resultBuffer = '';
        let errorBuffer = '';
        let mode = 'sql'; // 'sql', 'result', 'error'
        let seenSqlEnd = false;
        let seenResult = false;
        let seenError = false;
        let remainder = '';

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            let chunk = decoder.decode(value, { stream: true });
            chunk = remainder + chunk;
            remainder = '';

            // Process markers
            while (chunk.length > 0) {
                if (!seenSqlEnd) {
                    const sqlEndIdx = chunk.indexOf('--SQL-END--');
                    const errorIdx = chunk.indexOf('--ERROR--');
                    if (sqlEndIdx !== -1) {
                        sqlBuffer += chunk.substring(0, sqlEndIdx);
                        chunk = chunk.substring(sqlEndIdx + '--SQL-END--'.length);
                        seenSqlEnd = true;
                        mode = 'result';
                        sqlOutputCode.textContent = cleanSqlString(sqlBuffer);
                        if (window.Prism) Prism.highlightElement(sqlOutputCode);
                        continue;
                    } else if (errorIdx !== -1) {
                        errorBuffer += chunk.substring(errorIdx + '--ERROR--'.length);
                        chunk = '';
                        seenError = true;
                        mode = 'error';
                        break;
                    } else {
                        sqlBuffer += chunk;
                        chunk = '';
                        sqlOutputCode.textContent = cleanSqlString(sqlBuffer);
                        if (window.Prism) Prism.highlightElement(sqlOutputCode);
                        continue;
                    }
                } else if (mode === 'result') {
                    const resultIdx = chunk.indexOf('--RESULT--');
                    const errorIdx = chunk.indexOf('--ERROR--');
                    if (resultIdx !== -1) {
                        resultBuffer += chunk.substring(resultIdx + '--RESULT--'.length);
                        chunk = '';
                        seenResult = true;
                        break;
                    } else if (errorIdx !== -1) {
                        errorBuffer += chunk.substring(errorIdx + '--ERROR--'.length);
                        chunk = '';
                        seenError = true;
                        mode = 'error';
                        break;
                    } else {
                        resultBuffer += chunk;
                        chunk = '';
                        continue;
                    }
                } else if (mode === 'error') {
                    errorBuffer += chunk;
                    chunk = '';
                    break;
                } else {
                    // Should not reach here
                    chunk = '';
                }
            }

            // Show/hide results section as data arrives
            if (sqlBuffer.length > 0) {
                resultsSection.style.display = 'block';
            }
        }

        // Final UI state
        if (seenError || errorBuffer.trim()) {
            showError(errorBuffer.trim() || "An error occurred.");
            resultsSection.style.display = 'none';
        } else {
            if (sqlBuffer.length > 0) {
                sqlOutputCode.textContent = cleanSqlString(sqlBuffer);
                if (window.Prism) Prism.highlightElement(sqlOutputCode);
            }
            if (resultBuffer.length > 0) {
                resultOutput.innerHTML = marked.parse(resultBuffer);
                resultsSection.style.display = 'block';
            } else if (seenSqlEnd) {
                resultOutput.textContent = "-- Query executed successfully, but returned no data. --";
                resultsSection.style.display = 'block';
            }
        }

    } catch (error) {
        console.error("Query fetch or processing error:", error);
        showError(`An error occurred: ${error.message}`);
        resultsSection.style.display = 'none';
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

    showUploadStatus(`Starting upload of ${totalFiles} file(s)...`, 'info');

    for (let i = 0; i < totalFiles; i++) {
        const file = files[i];
        const currentFileNum = i + 1;

        showUploadStatus(`Uploading file ${currentFileNum}/${totalFiles}: ${file.name}...`, 'info');

        const allowedExtensions = ['.pdf', '.docx', '.txt', '.md'];
        const fileExtension = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();

        if (!allowedExtensions.includes(fileExtension)) {
             console.warn(`Skipping file ${file.name} due to invalid extension: ${fileExtension}`);
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

        } catch (error) {
            console.error(`Upload error for file ${file.name}:`, error);
            showUploadStatus(`Error uploading file ${currentFileNum}/${totalFiles}: ${file.name} - ${error.message}`, 'error');
            failedUploads++;
        }
    }

    // Final status update
    let finalMessage = `Finished uploads. ${successfulUploads}/${totalFiles} successful (${cumulativeChunks} total chunks added).`;
    let finalStatusType = 'success';
    if (failedUploads > 0) {
        finalMessage += ` ${failedUploads} failed.`;
        finalStatusType = successfulUploads > 0 ? 'warning' : 'error';
    }
    showUploadStatus(finalMessage, finalStatusType);
    fileInput.value = '';
    setUploadLoadingState(false);
}


// --- Utility Functions ---
function setLoadingState(isLoading) {
    submitButton.disabled = isLoading;
    if (isLoading) {
        loadingIndicator.style.display = 'flex';
    } else {
        loadingIndicator.style.display = 'none';
    }
}

function setUploadLoadingState(isLoading) {
    uploadButton.disabled = isLoading;
    fileInput.disabled = isLoading;
}

function showUploadStatus(message, type = 'info') {
    uploadStatus.textContent = message;
    uploadStatus.className = 'status-message'; // Reset classes
    if (type === 'success') {
        uploadStatus.classList.add('success');
    } else if (type === 'error') {
        uploadStatus.classList.add('error');
    } else if (type === 'warning'){
         uploadStatus.classList.add('warning');
    }
    uploadStatus.style.display = 'block';
}


function clearOutput() {
    // Clear the CODE element for SQL
    sqlOutputCode.textContent = '';
    resultOutput.innerHTML = '';
    errorOutput.textContent = '';
    errorOutput.style.display = 'none';
    resultsSection.style.display = 'none';
    // Keep upload status visible unless explicitly cleared
}

function showError(message) {
    errorOutput.textContent = message;
    errorOutput.style.display = 'block';
    resultsSection.style.display = 'none';
}

function cleanSqlString(rawSql) {
    if (!rawSql) return "";
    if (rawSql.trim().startsWith("ERROR:")) {
        return rawSql.trim();
    }
    // Remove leading ```sql, optional language specifier, and trailing ```
    let cleaned = rawSql.trim();
    cleaned = cleaned.replace(/^```(?:sql)?\s*/i, '');
    cleaned = cleaned.replace(/```\s*$/, '');
    return cleaned.trim();
}

// --- Initial setup ---
loadTheme();
clearOutput();
uploadStatus.style.display = 'none';