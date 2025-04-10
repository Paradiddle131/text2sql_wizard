// --- Query Elements ---
const queryInput = document.getElementById('query-input');
const submitButton = document.getElementById('submit-button');
const resultOutput = document.getElementById('result-output');
const errorOutput = document.getElementById('error-output');
const loadingIndicator = document.getElementById('loading-indicator');

// --- Upload Elements ---
const uploadForm = document.getElementById('upload-form');
const fileInput = document.getElementById('file-input');
const uploadButton = document.getElementById('upload-button');
const uploadStatus = document.getElementById('upload-status');

// --- Theme Elements ---
const themeToggleButton = document.getElementById('theme-toggle-button');

// --- API URLs ---
const QUERY_API_URL = '/api/query';
const UPLOAD_API_URL = '/api/upload_doc';

// --- Constants ---
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
uploadForm.addEventListener('submit', handleUploadSubmit); // Listener for upload form


// --- Query Submission Handler ---
async function handleQuerySubmit() {
    const queryText = queryInput.value.trim();
    if (!queryText) {
        showError("Please enter a query.");
        return;
    }

    setLoadingState(true);
    clearOutput(); // Clears previous query results and errors
    resultOutput.textContent = ''; // Explicitly clear result area

    console.log("Sending query:", queryText); // Log query start

    try {
        const response = await fetch(QUERY_API_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'text/plain' // Accept plain text stream
            },
            body: JSON.stringify({ query: queryText })
        });

        // Handle HTTP errors BEFORE trying to read body
        if (!response.ok) {
            let errorDetail = `Request failed with status ${response.status}`;
            try {
                const errorText = await response.text();
                console.error("Error response text:", errorText);
                try {
                     const jsonError = JSON.parse(errorText);
                     errorDetail = jsonError.detail || errorText || errorDetail;
                 } catch(e) {
                     errorDetail = errorText || errorDetail;
                 }
            } catch (readError) {
                console.error("Could not read error response body:", readError);
            }
            throw new Error(errorDetail); // Throw error to be caught below
        }

        // Process the stream only if response.ok
        if (!response.body) {
             throw new Error("Response body is missing.");
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let streaming = true;
        console.log("Starting to read query stream..."); // Log stream start

        while (streaming) {
            const { done, value } = await reader.read();
            if (done) {
                console.log("Query stream finished."); // Log stream end
                streaming = false;
                break;
            }
            const chunk = decoder.decode(value, { stream: true });
            // console.log('Received query chunk:', chunk); // Uncomment for verbose logging
            resultOutput.textContent += chunk; // Append text chunk
            resultOutput.scrollTop = resultOutput.scrollHeight; // Auto-scroll
        }

        if (resultOutput.textContent.length === 0) {
             console.log("Query stream ended but no content received.");
             showError("Received an empty SQL response from the server.");
        } else {
             console.log("Finished processing query stream content.");
        }

    } catch (error) {
        console.error("Query fetch or stream processing error:", error);
        showError(`An error occurred during SQL generation: ${error.message}`);
    } finally {
        setLoadingState(false); // Turn off loading indicator for query
        console.log("handleQuerySubmit finished.");
    }
}

// --- Document Upload Handler ---
async function handleUploadSubmit(event) {
    event.preventDefault(); // Prevent default form submission

    const files = fileInput.files; // Get the FileList object
    if (!files || files.length === 0) {
        showUploadStatus("Please select one or more files to upload.", true);
        return;
    }

    setUploadLoadingState(true); // Disable upload controls
    let successfulUploads = 0;
    let failedUploads = 0;
    const totalFiles = files.length;
    let cumulativeChunks = 0;

    showUploadStatus(`Starting upload of ${totalFiles} file(s)...`, false);

    // Process files one by one
    for (let i = 0; i < totalFiles; i++) {
        const file = files[i];
        const currentFileNum = i + 1;

        showUploadStatus(`Uploading file ${currentFileNum}/${totalFiles}: ${file.name}...`, false);

        // Client-side type check (optional but recommended)
        const allowedMimeTypes = [
            'application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'text/plain', 'text/markdown'
        ];
        const allowedExtensions = ['.pdf', '.docx', '.txt', '.md'];
        const fileExtension = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
        if (!allowedMimeTypes.includes(file.type) && !allowedExtensions.includes(fileExtension)) {
            console.warn(`Skipping file ${file.name} due to invalid type (MIME: ${file.type}, Ext: ${fileExtension})`);
            showUploadStatus(`Skipped file ${currentFileNum}/${totalFiles}: ${file.name} (invalid type).`, true);
            failedUploads++;
            continue; // Skip to the next file
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
                // Throw error to be caught below, include filename for context
                throw new Error(`(${file.name}) ${result.detail || `Upload failed status ${response.status}`}`);
            }

            // Log success for individual file
            console.log(`Successfully uploaded ${file.name}. Chunks: ${result.chunks_added}`);
            successfulUploads++;
            cumulativeChunks += result.chunks_added;
            // Update status slightly less frequently, or only on error/completion
            showUploadStatus(`Uploaded file ${currentFileNum}/${totalFiles}: ${file.name} (${result.chunks_added} chunks).`, false);


        } catch (error) {
            console.error(`Upload error for file ${file.name}:`, error);
            // Show error for the specific file, but continue loop
            showUploadStatus(`Error uploading file ${currentFileNum}/${totalFiles}: ${file.name} - ${error.message}`, true);
            failedUploads++;
        }
        // Optional short delay between uploads if needed
        // await new Promise(resolve => setTimeout(resolve, 100));
    }

    // Final status update after loop finishes
    let finalMessage = `Finished uploads. ${successfulUploads}/${totalFiles} successful (${cumulativeChunks} total chunks added).`;
    if (failedUploads > 0) {
        finalMessage += ` ${failedUploads} failed.`;
    }
    showUploadStatus(finalMessage, failedUploads > 0);
    fileInput.value = ''; // Clear the file input after processing all files
    setUploadLoadingState(false); // Re-enable upload controls
}


// --- Utility Functions ---
function setLoadingState(isLoading) {
    submitButton.disabled = isLoading; // Query submit button
    if (isLoading) {
        loadingIndicator.style.display = 'block';
    } else {
        loadingIndicator.style.display = 'none';
    }
}

function setUploadLoadingState(isLoading) {
    uploadButton.disabled = isLoading;
    fileInput.disabled = isLoading;
}

function showUploadStatus(message, isError = false) {
    uploadStatus.textContent = message;
    uploadStatus.style.color = isError ? 'var(--error-text-color)' : 'var(--text-color)'; // Use CSS variables
    uploadStatus.style.display = 'block';
    // Auto-hide success message after a delay? Maybe later.
    // if (!isError) {
    //     setTimeout(() => {
    //         uploadStatus.style.display = 'none';
    //     }, 5000); // Hide after 5 seconds
    // }
}

function clearOutput() {
    resultOutput.textContent = '';
    errorOutput.textContent = '';
    errorOutput.style.display = 'none';
    // Keep upload status visible unless explicitly cleared elsewhere
    // uploadStatus.textContent = '';
    // uploadStatus.style.display = 'none';
}

function showError(message) {
    errorOutput.textContent = message;
    errorOutput.style.display = 'block';
}

// --- Initial setup ---
loadTheme();
clearOutput(); // Clear query output/errors on load
showUploadStatus(''); // Clear upload status on load
uploadStatus.style.display = 'none'; // Hide upload status initially
