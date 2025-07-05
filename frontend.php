<?php
ini_set('display_errors', 1);
error_reporting(E_ALL & ~E_DEPRECATED & ~E_USER_DEPRECATED);

// Define the API URL for your Railway app to get document content
define('RAILWAY_API_BASE_URL', 'https://readserene-production.up.railway.app/get-doc-content');
define('RAILWAY_VOICES_API_URL', 'https://readserene-production.up.railway.app/get-google-tts-voices');
define('RAILWAY_TTS_API_URL', 'https://readserene-production.up.railway.app/synthesize-chapter-audio');

// Include your database connection file. Adjust path if necessary.
require_once("ato4_kot/dtcol.php");  //database structure assistance, not needed but still included in case it ever is

?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title id="documentTitle">Loading Document...</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="story_reader.css" rel="stylesheet" type="text/css">
</head>
<body>
    <div class="container">
        <div id="loadingMessage" class="text-center text-gray-600 mb-4">
            Getting contents...
        </div>
        <div id="errorMessage" class="text-red-600 font-bold mb-4" style="display:none;"></div>
        <div id="successMessage" class="text-green-600 font-bold mb-4" style="display:none;"></div>

        <div id="settingsGearContainer" class="absolute top-4 right-4 z-40" style="display:flex;">
            <button id="openVoiceSettingsBtn" class="text-white hover:text-blue-200 focus:outline-none">
                <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" fill="currentColor" class="bi bi-gear" viewBox="0 0 24 24">
                  <path d="M8 4.754a3.246 3.246 0 1 0 0 6.492 3.246 3.246 0 0 0 0-6.492M5.754 8a2.246 2.246 0 1 1 4.492 0 2.246 2.246 0 0 1-4.492 0"/>
                  <path d="M9.796 1.343c-.527-1.79-3.065-1.79-3.592 0l-.094.319a.873.873 0 0 1-1.255.52l-.292-.16c-1.64-.892-3.433.902-2.54 2.541l.159.292a.873.873 0 0 1-.52 1.255l-.319.094c-1.79.527-1.79 3.065 0 3.592l.319.094a.873.873 0 0 1 .52 1.255l-.16.292c-.892 1.64.901 3.434 2.541 2.54l.292.159a.873.873 0 0 1 1.255.52l.094.319c.527 1.79 3.065 1.79 3.592 0l.094-.319a.873.873 0 0 1 1.255-.52l.292.16c1.64.893 3.434-.902 2.54-2.541l-.159-.292a.873.873 0 0 1 .52-1.255l.319-.094c1.79-.527 1.79-3.065 0-3.592l-.319-.094a.873.873 0 0 1-.52-1.255l.16-.292c.893-1.64-.902-3.433-2.541-2.54l-.292.159a1.873 1.873 0 01-1.255-.52zm-2.633.283c.246-.835 1.428-.835 1.674 0l.094.319a1.873 1.873 0 002.693 1.115l.291-.16c.764-.415 1.6.42 1.184 1.185l-.159.292a1.873 1.873 0 001.116 2.692l.318.094c.835.246.835 1.428 0 1.674l-.319.094a1.873 1.873 0 00-1.115 2.693l.16.291c.415.764-.42 1.6-1.185 1.184l-.291-.159a1.873 1.873 0 00-2.693 1.116l-.094.318c-.246.835-1.428.835-1.674 0l-.094-.319a1.873 1.873 0 00-2.692-1.115l-.292.16c-.764.415-1.6-.42-1.184-1.185l.159-.291A1.873 1.873 0 001.945 8.93l-.319-.094c-.835-.246-.835-1.428 0-1.674l.319-.094A1.873 1.873 0 003.06 4.377l-.16-.292c-.415-.764.42-1.6 1.185-1.184l.292.159a1.873 1.873 0 002.692-1.115z"/>
                </svg>
            </button>
        </div>

        <div id="contentArea" style="display:none;">
            <div class="book-nav" id="bookNav">
                </div>

            <div id="voiceSelectionControls" style="display:none;">
                <h2 class="VoiceSelectiongText">Assign Voices to Characters for this Book</h2>
                <div id="noVoicesMessage" class="text-red-500 font-bold mb-4" style="display:none;">
                    No voices available for this book/document. Please contact contact support.
                </div>
                <div id="voiceMappingContainer">
                    </div>
                <button id="saveVoiceSettingsBtn" class="mt-4 px-6 py-2 bg-green-500 text-white font-semibold rounded-md shadow hover:bg-green-600 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2">
                    Save Voice Settings
                </button>
                <button id="closeVoiceSettingsBtn" class="mt-2 px-6 py-2 bg-gray-300 text-gray-800 font-semibold rounded-md shadow hover:bg-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-300 focus:ring-offset-2">
                    Close
                </button>
            </div>

            <div class="main-content-area" id="mainContentArea">
                <div id="chapterContentPanel" class="chapter-content-panel">
                    </div>
            </div>
        </div>
    </div>

    <div class="audio-player-controls px-4 py-3" id="audioPlayerControlsContainer" style="display:none;">
        <div class="audio-buttons-group"> 
            <button id="prevAudioBtn" class="audio-player-button" style="display:none;">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-rewind-fill" viewBox="0 0 16 16">
                  <path d="M8.404 7.304a.802.802 0 0 0 0 1.392l6.363 3.692c.52.302 1.233-.043 1.233-.696V4.308c0-.653-.713-.998-1.233-.696z"/>
                  <path d="M.404 7.304a.802.802 0 0 0 0 1.392l6.363 3.692c.52.302 1.233-.043 1.233-.696V4.308c0-.653-.713-.998-1.233-.696z"/>
                </svg>
            </button>

            <button id="playPauseBtn" class="audio-player-button" disabled>
                <svg id="playIcon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                <svg id="pauseIcon" style="display:none;" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
            </button>

            <button id="nextAudioBtn" class="audio-player-button" style="display:none;">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" class="bi bi-fast-forward-fill" viewBox="0 0 16 16">
                  <path d="M7.596 7.304a.802.802 0 0 1 0 1.392l-6.363 3.692C.713 12.69 0 12.345 0 11.692V4.308c0-.653.713-.998 1.233-.696z"/>
                  <path d="M15.596 7.304a.802.802 0 0 1 0 1.392l-6.363 3.692C8.713 12.69 8 12.345 8 11.692V4.308c0-.653.713-.998 1.233-.696z"/>
                </svg>
            </button>
        </div>
    </div>

    <div id="noVoicesMessage" class="text-center text-white text-lg font-semibold mt-8" style="display:none;">
        Please open voice settings to assign voices.
    </div>

    <script>
        // Constants for API URLs
        const RAILWAY_APP_API_KEY = 'removed-for-safety'; 
        const RAILWAY_API_URL = 'https://readserene-production.up.railway.app/get-doc-content';
        const RAILWAY_VOICES_API_URL = 'https://readserene-production.up.railway.app/get-google-tts-voices'; 
        const RAILWAY_TTS_API_URL = 'https://readserene-production.up.railway.app/synthesize-chapter-audio'; // Re-enabled in PHP

        // URLs for loading and saving voice settings via PHP backend
        const LOAD_VOICE_SETTINGS_URL = 'ato4_kot/load_voice_settings.php';
        const SAVE_VOICE_SETTINGS_URL = 'ato4_kot/save_voice_settings.php';

        // Global variables
        let allBookData = [];
        let chapterTextData = []; // Global variable for chapter JSON data as per user's instruction
        let googleVoicesData = {}; 
        let currentDocId = null; 
        let currentDocumentName = "Loading Document..."; 
        let currentBookObject = null; 
        let currentChapterObject = null; 
        let currentParagraphElements = []; // Stores ALL <p> and <hr> elements for the current chapter
        let totalVisualPages = 0; // Total count of visual pages in the current chapter
        let isPlaying = false; // Track play/pause state
        let activeVoiceId = null; // To store the selected voice ID (e.g., 'en-US-Wavenet-E')
        let activeVoiceName = null; // To store the selected voice Name (same as ID for simplicity here)
        let activeLanguageCode = null; // New: To store the language code (e.g., 'en-US')

        // NEW: Audio Playback Specific Globals for caching and sequential playback
        let audioPlayer = new Audio(); // Global Audio object instance
        let chapterAudioCache = {}; // Cache to store audio blobs per chapter index, structured as { chapterId: { pages: [{ audioUrl: "...", timestamps: [...] }], overallTimestamps: [...] } }
        let currentPlayingPage = 0; // Tracks the currently playing page index (0-based) within the chapter's audio segments
        let chapterOverallTimestamps = []; // Stores combined timestamps from all pages for easy navigation


        // Voice Presets (from story_reader_old.php, retained for voice settings UI)
        let voicePresets = {
            "Default Narrator (Female)": { voiceName: "en-US-Wavenet-E", languageCode: "en-US" },
            "Default Narrator (Male)": { voiceName: "en-US-Wavenet-D", languageCode: "en-US" },
        };
        
        // DOM Elements
        const chapterContentPanel = document.getElementById('chapterContentPanel');
        const documentTitleElement = document.getElementById('documentTitle'); 
        const mainContentArea = document.getElementById('mainContentArea'); 
        const bookNav = document.getElementById('bookNav');

        // Voice Settings UI Elements
        const openVoiceSettingsBtn = document.getElementById('openVoiceSettingsBtn'); 
        const voiceSelectionControls = document.getElementById('voiceSelectionControls');
        const closeVoiceSettingsBtn = document.getElementById('closeVoiceSettingsBtn');
        const applyPresetBtn = document.getElementById('applyPresetBtn'); 
        const voiceMappingContainer = document.getElementById('voiceMappingContainer'); 
        const saveVoiceSettingsBtn = document.getElementById('saveVoiceSettingsBtn');
        const noVoicesMessage = document.getElementById('noVoicesMessage');
        const settingsGearContainer = document.getElementById('settingsGearContainer'); 

        // Audio Player Controls
        const playPauseBtn = document.getElementById('playPauseBtn'); 
        const playIcon = document.getElementById('playIcon'); 
        const pauseIcon = document.getElementById('pauseIcon'); 
        const prevAudioBtn = document.getElementById('prevAudioBtn'); 
        const nextAudioBtn = document.getElementById('nextAudioBtn'); 
        const audioPlayerControlsContainer = document.getElementById('audioPlayerControlsContainer'); 


        // --- PAGE SIMULATION CONSTANTS (Dynamically retrieved from CSS) ---
        let PAGE_HEIGHT_PX;
        let PAGE_WIDTH_PX;
        let PAGE_PADDING_VERTICAL_PX;
        let PAGE_PADDING_HORIZONTAL_PX;
        let headerAreaStructuralHeight;
        let EFFECTIVE_PAGE_CONTENT_TEXT_HEIGHT_PX;

        // Function to measure CSS values
        function measureCssValues() {
            const tempInchDiv = document.createElement('div');
            tempInchDiv.style.width = '1in';
            tempInchDiv.style.visibility = 'hidden';
            tempInchDiv.style.position = 'absolute';
            document.body.appendChild(tempInchDiv); 
            const PIXELS_PER_INCH = tempInchDiv.offsetWidth;
            document.body.removeChild(tempInchDiv);

            const tempPageDiv = document.createElement('div');
            tempPageDiv.className = 'page'; 
            tempPageDiv.style.visibility = 'hidden';
            tempPageDiv.style.position = 'absolute';
            document.body.appendChild(tempPageDiv);
            PAGE_HEIGHT_PX = tempPageDiv.offsetHeight;
            PAGE_WIDTH_PX = tempPageDiv.offsetWidth;
            document.body.removeChild(tempPageDiv);

            const tempPaddingDiv = document.createElement('div');
            tempPaddingDiv.className = 'page-content-padding'; 
            tempPaddingDiv.style.visibility = 'hidden';
            tempPaddingDiv.style.position = 'absolute';
            tempPaddingDiv.style.width = `${PAGE_WIDTH_PX}px`; 
            document.body.appendChild(tempPaddingDiv);
            const computedPaddingStyle = getComputedStyle(tempPaddingDiv);
            PAGE_PADDING_VERTICAL_PX = parseFloat(computedPaddingStyle.paddingTop) + parseFloat(computedPaddingStyle.paddingBottom);
            PAGE_PADDING_HORIZONTAL_PX = parseFloat(computedPaddingStyle.paddingLeft) + parseFloat(computedPaddingStyle.paddingRight);
            document.body.removeChild(tempPaddingDiv);

            const tempParentForHeaderMeasure = document.createElement('div');
            tempParentForHeaderMeasure.style.visibility = 'hidden';
            tempParentForHeaderMeasure.style.position = 'absolute';
            tempParentForHeaderMeasure.style.top = '-9999px'; 
            tempParentForHeaderMeasure.style.left = '-9999px'; 
            tempParentForHeaderMeasure.style.width = `${PAGE_WIDTH_PX - PAGE_PADDING_HORIZONTAL_PX}px`;
            tempParentForHeaderMeasure.style.boxSizing = 'border-box'; 

            const tempHeaderArea = document.createElement('div');
            tempHeaderArea.className = 'header-area'; 
            
            const tempChapterTitleEl = document.createElement('h2');
            tempChapterTitleEl.className = 'chapter-title'; 
            tempChapterTitleEl.textContent = 'Chapter Title Placeholder'; 
            tempHeaderArea.appendChild(tempChapterTitleEl); 
            tempParentForHeaderMeasure.appendChild(tempHeaderArea); 
            
            document.body.appendChild(tempParentForHeaderMeasure);
            headerAreaStructuralHeight = tempHeaderArea.offsetHeight; 
            document.body.removeChild(tempParentForHeaderMeasure); 
            EFFECTIVE_PAGE_CONTENT_TEXT_HEIGHT_PX = PAGE_HEIGHT_PX - PAGE_PADDING_VERTICAL_PX - headerAreaStructuralHeight;
        }

        // --- Helper Functions ---
        function getDisplayableString(value) {
            if (value === null || typeof value === 'undefined') {
                return '';
            }
            return String(value).trim();
        }

        function htmlspecialchars(str) {
            if (typeof str !== 'string') {
                str = String(str);
            }
            const div = document.createElement('div');
            div.appendChild(document.createTextNode(str));
            return div.innerHTML;
        }

        function getChapterData(bookId, chapterId) {
            const book = allBookData.find(b => b.id === bookId);
            if (book) {
                const chapter = book.chapters.find(c => c.id === chapterId);
                return chapter || null;
            }
            return null;
        }

        function showMessage(type, message) {
            const successDiv = document.getElementById('successMessage');
            const errorDiv = document.getElementById('errorMessage');

            successDiv.style.display = 'none';
            errorDiv.style.display = 'none';

            if (type === 'success') {
                successDiv.textContent = message;
                successDiv.style.display = 'block';
            } else if (type === 'error') {
                errorDiv.textContent = message;
                errorDiv.style.display = 'block';
            }
            setTimeout(() => {
                successDiv.style.display = 'none';
                errorDiv.style.display = 'none';
            }, 5000);
        }

        /**
         * Updates the visibility of the play/pause and navigation buttons.
         * @param {boolean} contentLoaded True if document content is loaded.
         * @param {boolean} isPlayingState True if currently playing, false if paused.
         */
        function updatePlaybackControlVisibility(contentLoaded, isPlayingState) {
            if (contentLoaded) {
                audioPlayerControlsContainer.style.display = 'flex'; // Always show the container if content is loaded
                playPauseBtn.disabled = false; // Enable play button

                if (isPlayingState) {
                    playIcon.style.display = 'none';
                    pauseIcon.style.display = 'inline-block';
                    prevAudioBtn.style.display = 'inline-block'; // Show rewind
                    nextAudioBtn.style.display = 'inline-block'; // Show fast-forward
                } else {
                    playIcon.style.display = 'inline-block';
                    pauseIcon.style.display = 'none';
                    prevAudioBtn.style.display = 'none'; // Hide rewind
                    nextAudioBtn.style.display = 'none'; // Hide fast-forward
                }
            } else {
                audioPlayerControlsContainer.style.display = 'none'; // Hide container if no content
                playPauseBtn.disabled = true;
                prevAudioBtn.style.display = 'none';
                nextAudioBtn.style.display = 'none';
            }
        }

        /**
         * Fetches available Google TTS voices from the backend proxy.
         * This function is retained as it populates the voice selection UI.
         */
        async function fetchGoogleVoices() {
            try {
                const response = await fetch(RAILWAY_VOICES_API_URL, {
                    method: 'GET',
                    headers: {
                        'X-API-Key': RAILWAY_APP_API_KEY, 
                        'Content-Type': 'application/json'
                    }
                });

                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error(`Failed to fetch Google TTS voices: ${response.status} - ${errorText}`);
                }

                const data = await response.json();
                
                const allVoices = data.voices || [];

                // Filter for English Chirp voices as per the old file's logic
                const englishChirpVoices = allVoices.filter(voice => 
                    voice.languageCodes.some(lang => lang.startsWith('en-')) && 
                    voice.name.includes('Chirp')
                );

                googleVoicesData = englishChirpVoices.reduce((acc, voice) => {
                    const primaryLangCode = voice.languageCodes[0];
                    if (!acc[primaryLangCode]) {
                        acc[primaryLangCode] = [];
                    }
                    acc[primaryLangCode].push(voice);
                    return acc;
                }, {});

            } catch (error) {
                showMessage('error', `Error fetching voices: ${error.message}. Voice selection may not be available.`);
            }
        }

        /**
         * Parses the book's chapters to identify unique character names based on chapter titles.
         * This function is retained as it populates the voice selection UI.
         * Assumes chapter titles like "Character Name - Chapter Title".
         * @param {Object} book The book object.
         * @returns {Array<string>} An array of unique character names, including "Unknown".
         */
        function parseBookForCharacters(book) {
            const uniqueCharacterNames = new Set();
            uniqueCharacterNames.add("Unknown"); 

            if (book.chapters) {
                book.chapters.forEach(chapter => {
                    const chapterTitle = getDisplayableString(chapter.title);
                    const titleMatch = chapterTitle.match(/^(.+?)\s*-\s*(.+)$/); 
                    
                    if (titleMatch && titleMatch[1]) {
                        uniqueCharacterNames.add(titleMatch[1].trim());
                    }
                });
            }
            return Array.from(uniqueCharacterNames).sort((a, b) => {
                if (a === "Unknown") return 1; 
                if (b === "Unknown") return -1;
                return a.localeCompare(b);
            });
        }

        /**
         * Renders the voice selection form with dropdowns for each identified character.
         * This function is retained as it's part of the voice settings UI.
         * @param {Object} book The current book object, containing `characterNarationMap`.
         */
        function renderVoiceSelectionForm(book) {
            const uniqueCharacters = book.characterNarationMap; 
            const dropdownsContainer = voiceMappingContainer; 
            dropdownsContainer.innerHTML = ''; 

            if (!uniqueCharacters || uniqueCharacters.length === 0) {
                dropdownsContainer.innerHTML = '<p class="text-gray-600">No specific characters identified for voice assignment in this book.</p>';
                return;
            }

            uniqueCharacters.forEach(characterName => {
                const characterDiv = document.createElement('div');
                characterDiv.className = 'characterDiv';
                characterDiv.dataset.characterName = characterName;
                characterDiv.id = `character-voice-section-${characterName.replace(/[^a-zA-Z0-9]/g, '-')}`;

                const characterLabel = document.createElement('span');
                characterLabel.className = 'font-bold text-blue-900';
                characterLabel.textContent = characterName;
                characterDiv.appendChild(characterLabel);

                const langSelectId = `lang-select-${characterName.replace(/[^a-zA-Z0-9]/g, '-')}`;
                const langLabel = document.createElement('label');
                langLabel.htmlFor = langSelectId;
                langLabel.className = 'text-sm font-medium text-gray-700 mt-2';
                langLabel.textContent = `Accent/Language:`;
                characterDiv.appendChild(langLabel);

                const langSelect = document.createElement('select');
                langSelect.id = langSelectId;
                langSelect.name = langSelectId;
                langSelect.className = 'p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500';
                characterDiv.appendChild(langSelect);

                const defaultLangOption = document.createElement('option');
                defaultLangOption.value = "";
                defaultLangOption.textContent = "Select Accent/Language";
                langSelect.appendChild(defaultLangOption);

                const availableLangCodes = Object.keys(googleVoicesData).sort();
                availableLangCodes.forEach(langCode => {
                    const option = document.createElement('option');
                    option.value = langCode;
                    option.textContent = langCode;
                    langSelect.appendChild(option);
                });

                const voiceSelectId = `voice-select-${characterName.replace(/[^a-zA-Z0-9]/g, '-')}`;
                const voiceLabel = document.createElement('label');
                voiceLabel.htmlFor = voiceSelectId;
                voiceLabel.className = 'text-sm font-medium text-gray-700 mt-2';
                voiceLabel.textContent = `Voice:`;
                characterDiv.appendChild(voiceLabel);

                const voiceSelect = document.createElement('select');
                voiceSelect.id = voiceSelectId;
                voiceSelect.name = voiceSelectId;
                voiceSelect.className = 'p-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500';
                voiceSelect.disabled = true;
                characterDiv.appendChild(voiceSelect);

                const defaultVoiceOption = document.createElement('option');
                defaultVoiceOption.value = "";
                defaultVoiceOption.textContent = "Select Voice";
                voiceSelect.appendChild(defaultVoiceOption);

                langSelect.addEventListener('change', () => {
                    voiceSelect.innerHTML = '';
                    voiceSelect.appendChild(defaultVoiceOption.cloneNode(true));
                    voiceSelect.disabled = true;

                    const selectedLangCode = langSelect.value;
                    if (selectedLangCode && googleVoicesData[selectedLangCode]) {
                        const voicesForLang = googleVoicesData[selectedLangCode];
                        voicesForLang.forEach(voice => {
                            const option = document.createElement('option');
                            option.value = voice.name;
                            option.textContent = `${voice.name} (${voice.ssmlGender || 'Neutral'})`; 
                            option.dataset.languageCode = voice.languageCodes[0]; // Store language code on option
                            voiceSelect.appendChild(option);
                        });
                        voiceSelect.disabled = false;
                    }
                });

                dropdownsContainer.appendChild(characterDiv);
            });
        }

        /**
         * Loads saved voice selections from the PHP backend for the current book/document.
         * This function is retained as it's part of the voice settings UI.
         * If no selections are saved, it keeps the default dropdown states.
         * @param {string} bookTitle The title of the current book.
         * @param {string} docId The ID of the current document.
         */
        async function loadVoiceSelections(bookTitle, docId) {
            if (!docId) {
                console.warn("Doc ID is not available. Cannot load voice settings.");
                updatePlaybackControlVisibility(false, false); // Hide all controls
                noVoicesMessage.style.display = 'block'; // This message is inside the modal
                return;
            }
            
            try {
                const url = `${LOAD_VOICE_SETTINGS_URL}?book_id=${encodeURIComponent(bookTitle)}&doc_id=${encodeURIComponent(docId)}`;
                const response = await fetch(url);
                const data = await response.json();

                if (data.success && data.data && Object.keys(data.data).length > 0) {
                    let settingsApplied = false;

                    document.querySelectorAll('#voiceMappingContainer > div').forEach(charDiv => {
                        const characterName = charDiv.dataset.characterName;
                        if (!characterName) return;

                        let savedRegion = null;
                        let savedVoice = null;
                        // Iterate through the potential character settings (Character_1, Character_2, Character_3)
                        // to find the matching character name.
                        for (let i = 1; i <= 3; i++) { 
                            if (data.data[`Character_${i}`] === characterName) {
                                savedRegion = data.data[`Region_${i}`];
                                savedVoice = data.data[`Voice_${i}`];
                                break; // Found a match, exit loop
                            }
                        }

                        if (savedRegion && savedVoice) {
                            const langSelect = charDiv.querySelector('select[id^="lang-select-"]');
                            const voiceSelect = charDiv.querySelector('select[id^="voice-select-"]');

                            if (langSelect && voiceSelect) {
                                langSelect.value = savedRegion;
                                
                                // Manually dispatch change event to trigger voice dropdown population
                                const event = new Event('change');
                                langSelect.dispatchEvent(event); 

                                // Set the voice after a short delay to ensure the voice dropdown is populated
                                setTimeout(() => { 
                                    voiceSelect.value = savedVoice;
                                    if (voiceSelect.value === savedVoice) {
                                        settingsApplied = true;
                                        // Set active voice and language code when a voice is successfully loaded/applied
                                        activeVoiceId = savedVoice;
                                        activeVoiceName = savedVoice; // Assuming voiceName is same as voiceId
                                        activeLanguageCode = savedRegion; // Set the language code
                                    } else {
                                        console.warn(`Could not set saved voice "${savedVoice}" for character "${characterName}". It might not be available in the fetched Google voices.`);
                                    }
                                }, 500); // Increased delay to 500ms
                            }
                        }
                    });

                    // After attempting to apply settings, decide UI visibility of audio controls and message
                    setTimeout(() => {
                        if (settingsApplied) {
                            // Voices successfully loaded and applied
                            updatePlaybackControlVisibility(true, isPlaying); // Show play button, hide others initially
                            noVoicesMessage.style.display = 'none'; // Hide message within modal
                        } else {
                            // No relevant settings found or applied (could be no data, or data didn't match current characters)
                            updatePlaybackControlVisibility(false, false); // Hide all controls
                            noVoicesMessage.style.display = 'block'; // Show message within modal
                        }
                    }, 600); 
                } else {
                    // No saved voice settings found for this book at all (data.success is false or data is empty)
                    console.log('No saved voice settings found for this book in the database. Showing "no voices" message.', data.message);
                    updatePlaybackControlVisibility(false, false); // Hide all controls
                    noVoicesMessage.style.display = 'block'; // Show message within modal
                }
            } catch (error) {
                console.error("Error loading voice settings:", error);
                showMessage('error', `Error loading voice settings: ${error.message}`);
                updatePlaybackControlVisibility(false, false); // Hide all controls
                noVoicesMessage.style.display = 'block'; // Show message within modal
            }
        }

        /**
         * Saves the current voice selections to the PHP backend.
         * This function is retained as it's part of the voice settings UI.
         * @param {string} bookTitle The title of the current book.
         * @param {string} docId The ID of the current document.
         */
        async function saveVoiceSelections(bookTitle, docId) {
            if (!docId) {
                showMessage('error', "Cannot save: Document ID is not available.");
                console.error("Doc ID is not available for saving voice settings.");
                return;
            }

            const characterSettingsToSave = [];
            document.querySelectorAll('#voiceMappingContainer > div').forEach(charDiv => {
                const characterName = charDiv.dataset.characterName;
                const langSelect = charDiv.querySelector('select[id^="lang-select-"]');
                const voiceSelect = charDiv.querySelector('select[id^="voice-select-"]');

                if (characterName && langSelect && voiceSelect && langSelect.value && voiceSelect.value) {
                    characterSettingsToSave.push({
                        name: characterName,
                        region: langSelect.value,
                        voice: voiceSelect.value
                    });
                }
            });

            try {
                const response = await fetch(SAVE_VOICE_SETTINGS_URL, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        book_id: bookTitle, 
                        doc_id: docId,
                        character_settings: characterSettingsToSave
                    })
                });
                const data = await response.json();

                if (data.success) {
                    showMessage('success', data.message);
                    voiceSelectionControls.style.display = 'none'; // Hide the form on successful save
                    settingsGearContainer.style.display = 'flex'; // Show the gear icon container
                    // After saving, reload voice selections to update UI state (enable/disable play button)
                    await loadVoiceSelections(bookTitle, currentDocId);
                } else {
                    showMessage('error', data.message);
                    console.error("Failed to save voice settings:", data.message);
                    // If save fails, keep the modal open for user to correct
                    voiceSelectionControls.style.display = 'flex'; 
                    settingsGearContainer.style.display = 'none'; 
                    updatePlaybackControlVisibility(false, false); // Hide all controls
                }
            } catch (error) {
                console.error("Error saving voice settings:", error);
                showMessage('error', `Error saving voice settings: ${error.message}`);
                // If error, keep the modal open
                voiceSelectionControls.style.display = 'flex';
                settingsGearContainer.style.display = 'none'; 
                updatePlaybackControlVisibility(false, false); // Hide all controls
            }
        }

        /**
         * Renders the content of a chapter by creating multiple visual pages
         * and appending them all to the chapterContentPanel.
         * This directly replicates the old file's `renderChapterAsPage` logic for visual display.
         * @param {string} bookId The ID of the current book.
         * @param {string} chapterId The ID of the current chapter.
         */
        function renderChapterContent(bookId, chapterId) { 
            const chapter = getChapterData(bookId, chapterId);
            if (!chapter || !chapter.content) {
                chapterContentPanel.innerHTML = '<p class="text-red-500">Chapter not found or no content available.</p>';
                currentParagraphElements = []; // Clear elements
                totalVisualPages = 0;
                updatePlaybackControlVisibility(false, false); // Hide all controls if no content
                return;
            }

            currentChapterObject = chapter;

            // Update the document title with full context
            if (documentTitleElement && currentBookObject && currentDocumentName !== "Loading Document...") { 
                const docName = currentDocumentName; 
                const bookTitle = currentBookObject.title || 'Book';
                const chapterNumber = getDisplayableString(chapter.number);
                let newTitle = `${docName} - ${bookTitle}`;
                if (chapterNumber && chapterNumber !== "0") {
                    newTitle += ` - ${chapterNumber}`; 
                }
                documentTitleElement.textContent = newTitle;
            } else {
                documentTitleElement.textContent = "Loading Document..."; 
            }

            chapterContentPanel.innerHTML = ''; // Clear current content

            // Create a temporary div to parse the raw chapter HTML and extract p/hr elements
            const tempContentDiv = document.createElement('div');
            tempContentDiv.innerHTML = chapter.content; 
            currentParagraphElements = Array.from(tempContentDiv.querySelectorAll('p, hr'));
            
            let currentPageElementIndex = 0; // Index in currentParagraphElements (P or HR)
            let pageCounter = 0; // Visual page counter

            // Create a temporary off-screen container to measure elements without affecting layout
            const measurementContainer = document.createElement('div');
            measurementContainer.style.visibility = 'hidden';
            measurementContainer.style.position = 'absolute';
            measurementContainer.style.top = '-9999px';
            measurementContainer.style.left = '-9999px';
            measurementContainer.style.width = `${PAGE_WIDTH_PX - PAGE_PADDING_HORIZONTAL_PX}px`; 
            measurementContainer.style.boxSizing = 'border-box'; 
            document.body.appendChild(measurementContainer);

            // Create a temporary page-content-text div for measurement
            const tempPageContentTextDiv = document.createElement('div');
            tempPageContentTextDiv.className = 'page-content-text'; // Changed from chapter-text
            tempPageContentTextDiv.style.overflow = 'hidden'; // Hide overflow for measurement
            measurementContainer.appendChild(tempPageContentTextDiv);

            // Loop to create and append pages
            while (currentPageElementIndex < currentParagraphElements.length) {
                pageCounter++;
                totalVisualPages = pageCounter; // Update total page count

                const pageDiv = document.createElement('div');
                pageDiv.className = 'page';
                pageDiv.dataset.pageNumber = pageCounter;

                const pageContentPaddingDiv = document.createElement('div');
                pageContentPaddingDiv.className = 'page-content-padding';

                const pageContentTextDiv = document.createElement('div');
                pageContentTextDiv.className = 'page-content-text'; // Changed from chapter-text

                // Add chapter header to the first page only
                if (pageCounter === 1) { 
                    const headerArea = document.createElement('div');
                    headerArea.className = 'header-area';
                    const chapterTitleEl = document.createElement('h2');
                    chapterTitleEl.className = 'chapter-title';
                    const chapterTitle = getDisplayableString(chapter.title);
                    const chapterNumber = getDisplayableString(chapter.number);

                    let displayTitle = '';
                    if (chapterNumber && chapterNumber !== "0") {
                        displayTitle += `${chapterNumber}. `;
                    }
                    displayTitle += chapterTitle;
                    chapterTitleEl.textContent = displayTitle;

                    headerArea.appendChild(chapterTitleEl);
                    pageContentPaddingDiv.appendChild(headerArea);
                }

                pageContentPaddingDiv.appendChild(pageContentTextDiv);
                pageDiv.appendChild(pageContentPaddingDiv);
                
                tempPageContentTextDiv.innerHTML = ''; // Clear for new page measurement
                
                let elementsAddedToPage = 0; 
                for (let i = currentPageElementIndex; i < currentParagraphElements.length; i++) {
                    const elementToAppend = currentParagraphElements[i];
                    const clonedElement = elementToAppend.cloneNode(true);
                    
                    tempPageContentTextDiv.appendChild(clonedElement);

                    // Check if adding this element overflows the effective content height
                    if (tempPageContentTextDiv.scrollHeight > EFFECTIVE_PAGE_CONTENT_TEXT_HEIGHT_PX + 0.5 && tempPageContentTextDiv.children.length > 1) { 
                        tempPageContentTextDiv.removeChild(clonedElement); // Remove the overflowing element
                        break; // This paragraph starts the next page
                    } else {
                        // If it fits, add the *original* element to the actual pageContentTextDiv
                        pageContentTextDiv.appendChild(elementToAppend);
                        elementsAddedToPage++;
                    }
                }
                
                // If no elements were added to the current page (e.g., end of chapter, or very large single element)
                // and there's still content left, it means the last element was too big for the previous page
                // and it should be on this new page.
                if (elementsAddedToPage === 0 && currentPageElementIndex < currentParagraphElements.length) {
                    const elementToAppend = currentParagraphElements[currentPageElementIndex];
                    pageContentTextDiv.appendChild(elementToAppend);
                    elementsAddedToPage++;
                }

                currentPageElementIndex += elementsAddedToPage; // Move the overall element cursor
                chapterContentPanel.appendChild(pageDiv); // Add the constructed page to the DOM
            }
            
            // Remove the temporary measurement container from the DOM
            document.body.removeChild(measurementContainer);

            // After rendering content, update playback control visibility
            updatePlaybackControlVisibility(true, isPlaying);
            
            // User's instruction: Fill chapterTextData when chapter's pages are done loading their content
            chapterTextData.length = 0; // Clear the array as per user instruction
            const pages = document.querySelectorAll('.page');
            pages.forEach(page => {
                const pageNumber = parseInt(page.getAttribute('data-page-number'));
                const paragraphs = page.querySelectorAll('p'); // Assuming 'p' tags contain the text for synthesis

                paragraphs.forEach((p, index) => {
                    const text = p.textContent.trim();
                    if (text) {
                        let paragraphType = 'narration'; // Default type
                        // Add logic to determine paragraphType if needed (e.g., dialogue, italicised)
                        const italicNode = p.querySelector('em, i');
                        const italicOnly = italicNode && italicNode.textContent.trim() === text;
                        const hasQuote = /["“”][^"“”]+["“”]/.test(text);

                        if (italicOnly) {
                            paragraphType = 'italicised';
                        } else if (hasQuote) {
                            paragraphType = 'dialogue';
                        }

                        chapterTextData.push({
                            pageNumber: pageNumber,
                            paragraphIndexOnPage: index,
                            paragraphType: paragraphType,
                            text: text
                        });
                    }
                });
            });
            console.log("chapterTextData filled for current chapter:", chapterTextData);
        }

        /**
         * Function to display the contents of a selected book (chapters).
         * This function is now defined before renderContent.
         */
        function displayBookContents(book) {
            currentBookObject = book;

            mainContentArea.innerHTML = '';

            const chapterNavWrapper = document.createElement('div');
            chapterNavWrapper.className = 'chapter-nav-wrapper';

            const chapterNavTitle = document.createElement('h3');
            chapterNavTitle.textContent = htmlspecialchars(book.title) + ' Chapters:';
            chapterNavWrapper.appendChild(chapterNavTitle);

            let firstDisplayableChapter = null;
            if (book.chapters && book.chapters.length > 0) {
                const hasExplicitChapters = book.chapters.some(chapter => chapter.number !== "0");

                book.chapters.forEach((chapter) => {
                    if (chapter.title.toLowerCase() === "introduction" && chapter.number === "0") {
                        return; 
                    }

                    const chapterButton = document.createElement('button');
                    chapterButton.className = `chapter-button`;
                    chapterButton.dataset.chapterId = htmlspecialchars(chapter.id);
                    chapterButton.dataset.bookId = htmlspecialchars(book.id);
                    
                    const chapterNumDisplay = (hasExplicitChapters && chapter.number === "0") ? "" : `${chapter.number} `;
                    chapterButton.innerHTML = htmlspecialchars(`${chapterNumDisplay}${chapter.title}`);
                    
                    chapterButton.addEventListener('click', (event) => {
                        document.querySelectorAll('.chapter-button').forEach(btn => btn.classList.remove('active'));
                        event.currentTarget.classList.add('active');
                        const bookId = event.currentTarget.dataset.bookId;
                        const chapterId = event.currentTarget.dataset.chapterId;
                        
                        // Reset buttons and stop audio when a new chapter is clicked
                        if (audioPlayer) {
                            audioPlayer.pause();
                            audioPlayer.src = ''; // Clear current audio source
                        }
                        isPlaying = false;
                        playIcon.style.display = 'inline-block';
                        pauseIcon.style.display = 'none';
                        prevAudioBtn.style.display = 'none';
                        nextAudioBtn.style.display = 'none';
                        playPauseBtn.disabled = false; // Enable play button for new chapter
                        
                        chapterAudioCache = {}; // Clear audio cache for the new chapter
                        chapterTextData.length = 0; // Clear chapterTextData for the new chapter as per user instruction
                        chapterOverallTimestamps = []; // Clear overall timestamps for the new chapter
                        currentPlayingPage = 0; // Reset current playing page index
                        
                        renderChapterContent(bookId, chapterId);
                    });

                    chapterNavWrapper.appendChild(chapterButton);

                    if (!firstDisplayableChapter && !(hasExplicitChapters && chapter.number === "0")) { 
                        firstDisplayableChapter = chapter;
                    }
                });
            } else {
                console.warn("No chapters found for this book.");
                bookNav.innerHTML = '<p class="text-gray-600">No Books/Tabs found in the document. Check your document structure or API response.</p>';
            }
            mainContentArea.appendChild(chapterNavWrapper);

            chapterContentPanel.innerHTML = ''; 
            mainContentArea.appendChild(chapterContentPanel); 
            if (firstDisplayableChapter) {
                renderChapterContent( 
                    book.id,
                    firstDisplayableChapter.id
                );
                setTimeout(() => {
                    const initialChapterButton = chapterNavWrapper.querySelector(`.chapter-button[data-chapter-id="${firstDisplayableChapter.id}"]`);
                    if(initialChapterButton) {
                        initialChapterButton.classList.add('active');
                    }
                }, 0);
            } else {
                console.warn("No displayable chapters in this book.");
                chapterContentPanel.innerHTML = '<p class="text-gray-600">No content to display for this book.</p>';
                updatePlaybackControlVisibility(false, false); // Hide controls if no displayable chapters
            }
        }

        async function renderContent(data) {
            document.getElementById('loadingMessage').style.display = 'none';
            document.getElementById('contentArea').style.display = 'block';
            
            currentDocId = data.document_id || null; 
            currentDocumentName = data.title || "Untitled Document"; 
            
            if (!currentDocId) {
                showMessage('error', 'Warning: Document ID not found. Voice saving/loading might be limited.');
            }

            allBookData = data.books || [];
            
            const bookNav = document.getElementById('bookNav');
            bookNav.innerHTML = '';

            if (allBookData.length === 0) {
                bookNav.innerHTML = '<p>No Books/Tabs found in the document. Check your document structure or API response.</p>';
                updatePlaybackControlVisibility(false, false); // Hide audio controls if no books
                return;
            }

            await fetchGoogleVoices(); 

            allBookData.forEach((book, bookIndex) => {
                const bookButton = document.createElement('button');
                bookButton.className = `book-button ${bookIndex === 0 ? 'active' : ''}`;
                bookButton.dataset.bookId = getDisplayableString(book.id); 
                bookButton.dataset.bookTitle = getDisplayableString(book.title); 
                bookButton.textContent = htmlspecialchars(book.title);
                
                book.characterNarationMap = parseBookForCharacters(book); 

                bookButton.addEventListener('click', async (event) => {
                    document.querySelectorAll('.book-button').forEach(btn => btn.classList.remove('active'));
                    event.currentTarget.classList.add('active');

                    // Call displayBookContents here, now that it's defined
                    displayBookContents(book); 
                    
                    renderVoiceSelectionForm(book); 
                    // Use book.title directly from the object
                    await loadVoiceSelections(book.title, currentDocId); 
                });
                bookNav.appendChild(bookButton); 
            });

            // Event listener for saving voice settings
            document.getElementById('saveVoiceSettingsBtn').addEventListener('click', async () => {
                // Use currentBookObject.title which is set by displayBookContents
                if (currentBookObject && currentBookObject.title) {
                    const bookTitle = currentBookObject.title;
                    await saveVoiceSelections(bookTitle, currentDocId);
                } else {
                    showMessage('error', 'No book selected to save settings for.');
                }
            });

            // Event listener for opening voice settings modal
            openVoiceSettingsBtn.addEventListener('click', async () => {
                voiceSelectionControls.style.display = 'flex'; 
                settingsGearContainer.style.display = 'none'; 
                updatePlaybackControlVisibility(false, false); // Hide audio controls when settings are open

                // Use currentBookObject.title
                if (currentBookObject && currentBookObject.title && currentDocId) { 
                    renderVoiceSelectionForm(currentBookObject); // Re-render form for current book
                    await loadVoiceSelections(currentBookObject.title, currentDocId); 
                } else {
                    voiceMappingContainer.innerHTML = '<p class="text-gray-600">Please select a book to configure voices.</p>';
                    noVoicesMessage.style.display = 'block'; 
                }
            });

            // Event listener for closing voice settings modal
            closeVoiceSettingsBtn.addEventListener('click', () => {
                voiceSelectionControls.style.display = 'none';
                settingsGearContainer.style.display = 'flex';
                // Re-evaluate showing audio controls based on whether voices are loaded
                // Use currentBookObject.title
                if (currentBookObject && currentBookObject.title && currentDocId) {
                    loadVoiceSelections(currentBookObject.title, currentDocId);
                } else {
                    updatePlaybackControlVisibility(false, false);
                }
            });

            // Helper to play audio for a specific page
            function playPageAudio(chapterId, pageIndex) {
                const chapterCachedData = chapterAudioCache[chapterId];
                if (chapterCachedData && chapterCachedData.pages && chapterCachedData.pages[pageIndex]) {
                    const pageData = chapterCachedData.pages[pageIndex];
                    audioPlayer.src = pageData.audioUrl;
                    audioPlayer.load();
                    audioPlayer.play();
                    isPlaying = true;
                    updatePlaybackControlVisibility(true, true);
                    console.log(`Playing audio for chapter ${chapterId}, page ${pageIndex + 1}`);
                } else {
                    console.warn(`No audio found for chapter ${chapterId}, page ${pageIndex + 1}.`);
                    isPlaying = false;
                    updatePlaybackControlVisibility(true, false);
                    // Optionally, try to play next page if current one is missing
                    if (pageIndex + 1 < chapterCachedData.pages.length) { // Check against cached pages length
                         playPageAudio(chapterId, pageIndex + 1);
                    }
                }
            }


            // NEW FUNCTION: Synthesize and play chapter audio (Point 1, 2, 3, 4)
            async function synthesizeAndPlayChapterAudio(chapterId) {
                const chapter = getChapterData(currentBookObject.id, chapterId);

                if (!chapter || !activeVoiceId || !activeLanguageCode) {
                    console.warn("Cannot synthesize audio: Missing chapter data, active voice, or language code.");
                    showMessage('error', 'Please select a voice in settings to enable audio playback.');
                    updatePlaybackControlVisibility(true, false); // Show controls, but disabled
                    return;
                }

                if (!chapterTextData || chapterTextData.length === 0) {
                    console.warn("Cannot synthesize audio: No paragraph data available for the current chapter.");
                    showMessage('error', 'No text content found for this chapter to synthesize audio.');
                    updatePlaybackControlVisibility(true, false);
                    return;
                }

                // Point 3: Check if chapter audio for all pages is already cached
                if (chapterAudioCache[chapterId] && chapterAudioCache[chapterId].pages && chapterAudioCache[chapterId].pages.length > 0) {
                    console.log(`Playing cached audio for chapter: ${chapterId}`);
                    currentPlayingPage = 0; // Start from the first page
                    playPageAudio(chapterId, currentPlayingPage); // Play the first cached page audio
                    return;
                }

                // If not cached, proceed with synthesis for the entire chapter
                playPauseBtn.disabled = true;
                playIcon.style.display = 'none';
                pauseIcon.style.display = 'inline-block'; // Show loading state visually
                showMessage('success', 'Synthesizing audio...');

                try {
                    const payloadToSend = {
                        documentId: currentDocId,
                        chapterId: chapterId,
                        voiceName: activeVoiceId,
                        languageCode: activeLanguageCode,
                        chapterParagraphs: chapterTextData // This JSON contains per-page info
                    };

                    console.log("Sending synthesis request with payload:", payloadToSend);

                    const response = await fetch(RAILWAY_TTS_API_URL, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-API-Key': RAILWAY_APP_API_KEY
                        },
                        body: JSON.stringify(payloadToSend)
                    });

                    if (!response.ok) {
                        const errorText = await response.text();
                        throw new Error(`HTTP error! status: ${response.status}, Message: ${errorText}`);
                    }

                    const data = await response.json();
                    console.log("Synthesis response:", data);

                    if (data.pageAudioResponses && data.pageAudioResponses.length > 0) {
                        chapterAudioCache[chapterId] = { pages: [] };
                        chapterOverallTimestamps = []; // Clear previous timestamps

                        let cumulativeTimeMs = 0; // For accumulating timestamps across pages

                        for (const pageResponse of data.pageAudioResponses) {
                            if (pageResponse.audioContent && pageResponse.format) {
                                const audioUrl = `data:${pageResponse.format};base64,${pageResponse.audioContent}`;
                                
                                // Create a temporary audio element to get duration
                                const pageAudioTemp = new Audio(audioUrl);
                                await new Promise(resolve => {
                                    pageAudioTemp.onloadedmetadata = () => {
                                        pageAudioTemp.durationMs = pageAudioTemp.duration * 1000; // Store duration in ms
                                        resolve();
                                    };
                                    pageAudioTemp.onerror = () => {
                                        console.error("Error loading page audio for duration calculation. Defaulting to 0.");
                                        pageAudioTemp.durationMs = 0; // Default to 0 on error
                                        resolve();
                                    };
                                });
                                
                                const pageTimestamps = pageResponse.timestamps || [];
                                const adjustedTimestamps = pageTimestamps.map(ts => ({
                                    markName: ts.markName,
                                    timeMs: ts.timeMs + cumulativeTimeMs // Adjust timestamp relative to start of chapter
                                }));

                                chapterAudioCache[chapterId].pages.push({
                                    audioUrl: audioUrl,
                                    timestamps: pageTimestamps, // Original timestamps relative to page start
                                    durationMs: pageAudioTemp.durationMs // Duration of this specific page's audio
                                });
                                
                                chapterOverallTimestamps = chapterOverallTimestamps.concat(adjustedTimestamps);
                                cumulativeTimeMs += pageAudioTemp.durationMs; // Add this page's duration to cumulative

                            } else {
                                console.warn("Missing audioContent or format in a pageAudioResponse.");
                            }
                        }

                        if (chapterAudioCache[chapterId].pages.length > 0) {
                            currentPlayingPage = 0; // Start from the first page
                            playPageAudio(chapterId, currentPlayingPage); // Play the first page
                            showMessage('success', 'Audio ready!');
                        } else {
                            throw new Error('No valid page audio responses received for synthesis.');
                        }

                    } else {
                        throw new Error('Backend response missing pageAudioResponses array or it is empty.');
                    }
                } catch (error) {
                    console.error("Error during audio synthesis:", error);
                    showMessage('error', `Audio synthesis failed: ${error.message}`);
                    isPlaying = false;
                    updatePlaybackControlVisibility(true, false);
                    playIcon.style.display = 'inline-block';
                    pauseIcon.style.display = 'none';
                    chapterAudioCache[chapterId] = { pages: [] }; // Clear cache on error
                }
            }

            // Play/Pause button logic (Point 3)
            playPauseBtn.addEventListener('click', async () => {
                const currentChapterId = currentChapterObject ? currentChapterObject.id : null;
                if (!currentChapterId) {
                    showMessage('error', 'No chapter loaded to play audio.');
                    return;
                }

                if (isPlaying) {
                    // If currently playing, pause it
                    audioPlayer.pause();
                    isPlaying = false;
                } else {
                    // If not playing (either paused or not started)
                    if (audioPlayer.src && audioPlayer.paused) {
                        // If there's an audio source and it's paused, resume playback
                        audioPlayer.play();
                        isPlaying = true;
                    } else {
                        // If no audio source or not paused (e.g., first play or after audio ended),
                        // synthesize and play new audio for the current chapter.
                        await synthesizeAndPlayChapterAudio(currentChapterId);
                    }
                }
                updatePlaybackControlVisibility(true, isPlaying);
            });

            // Handle audio ending (Point 4)
            audioPlayer.addEventListener('ended', () => {
                const currentChapterId = currentChapterObject ? currentChapterObject.id : null;
                if (!currentChapterId) {
                    isPlaying = false;
                    updatePlaybackControlVisibility(true, false);
                    showMessage('info', 'Chapter audio finished.');
                    return;
                }

                const chapterCachedData = chapterAudioCache[currentChapterId];
                if (chapterCachedData && chapterCachedData.pages) {
                    currentPlayingPage++; // Move to the next page
                    if (currentPlayingPage < chapterCachedData.pages.length) {
                        playPageAudio(currentChapterId, currentPlayingPage);
                    } else {
                        // All pages in the chapter have finished
                        isPlaying = false;
                        updatePlaybackControlVisibility(true, false);
                        showMessage('info', 'Chapter audio finished.');
                        currentPlayingPage = 0; // Reset for next play
                        // Optionally, automatically advance to next chapter here
                    }
                } else {
                    // No cached pages, fallback to general ended state
                    isPlaying = false;
                    updatePlaybackControlVisibility(true, false);
                    showMessage('info', 'Chapter audio finished.');
                }
            });

            // Fast-forward button logic (Point 2)
            nextAudioBtn.addEventListener('click', () => {
                if (chapterOverallTimestamps.length === 0) {
                    showMessage('info', 'No timestamp data available for navigation.');
                    return;
                }

                let currentOverallTimeMs = audioPlayer.currentTime * 1000;
                let nextParagraphTimeMs = -1;

                // Find the next paragraph's timestamp
                for (const ts of chapterOverallTimestamps) {
                    // Add a small buffer (e.g., 50ms) to avoid replaying the current mark
                    if (ts.timeMs > currentOverallTimeMs + 50) { 
                        nextParagraphTimeMs = ts.timeMs;
                        break;
                    }
                }

                if (nextParagraphTimeMs !== -1) {
                    audioPlayer.currentTime = nextParagraphTimeMs / 1000;
                    if (audioPlayer.paused) audioPlayer.play(); // Auto-play if paused
                    isPlaying = true;
                    updatePlaybackControlVisibility(true, true);
                } else {
                    showMessage('info', 'Reached end of audio.');
                    isPlaying = false;
                    updatePlaybackControlVisibility(true, false);
                }
            });

            // Rewind button logic (Point 2)
            prevAudioBtn.addEventListener('click', () => {
                if (chapterOverallTimestamps.length === 0) {
                    showMessage('info', 'No timestamp data available for navigation.');
                    return;
                }

                let currentOverallTimeMs = audioPlayer.currentTime * 1000;
                let prevParagraphTimeMs = -1;

                // Find the previous paragraph's timestamp
                // Iterate backwards from the current position
                for (let i = chapterOverallTimestamps.length - 1; i >= 0; i--) {
                    const ts = chapterOverallTimestamps[i];
                    // If current time is past this timestamp (with a small buffer), this is the previous one
                    if (ts.timeMs < currentOverallTimeMs - 50) { 
                        prevParagraphTimeMs = ts.timeMs;
                        break;
                    }
                }
                
                // If no previous paragraph found (e.g., at the very beginning), rewind to start
                if (prevParagraphTimeMs === -1 && chapterOverallTimestamps.length > 0) {
                    prevParagraphTimeMs = chapterOverallTimestamps[0].timeMs; // Go to the very first timestamp
                }

                if (prevParagraphTimeMs !== -1) {
                    audioPlayer.currentTime = prevParagraphTimeMs / 1000;
                    if (audioPlayer.paused) audioPlayer.play();
                    isPlaying = true;
                    updatePlaybackControlVisibility(true, true);
                } else {
                    // Already at the very beginning
                    audioPlayer.currentTime = 0;
                    showMessage('info', 'Already at the beginning of the chapter.');
                }
            });


            // Simulate a click on the first book button to load its content initially
            const firstBookButton = document.querySelector('.book-button');
            if (firstBookButton) {
                firstBookButton.click(); 
            }
        }
        
        // Main DOMContentLoaded event listener
        document.addEventListener('DOMContentLoaded', async () => {
            measureCssValues(); // Measure dynamic CSS values once

            // Initially hide all audio controls and disable play button
            updatePlaybackControlVisibility(false, false);

            try {
                // Fetch main document content from Railway API
                const response = await fetch(RAILWAY_API_URL, {
                    method: 'GET',
                    headers: {
                        'X-API-Key': RAILWAY_APP_API_KEY,
                        'Content-Type': 'application/json'
                    }
                });

                if (!response.ok) {
                    const errorJson = await response.json();
                    let errorMessage = errorJson.error || `HTTP error! Status: ${response.status}`;
                    throw new Error(errorMessage);
                }

                const data = await response.json();
                renderContent(data); // Render the fetched content and set up playback correctly.

                // Ensure currentBookObject and currentDocId are set for loadVoiceSelections
                if (currentBookObject && currentBookObject.title && currentDocId) {
                    await loadVoiceSelections(currentBookObject.title, currentDocId);
                } else {
                    // If no active book on load, ensure audio controls are hidden and message shown
                    updatePlaybackControlVisibility(false, false);
                    noVoicesMessage.style.display = 'block'; 
                }

            } catch (error) {
                // Handle any errors during initial fetch or rendering
                console.error("DOMContentLoaded: Failed to fetch document content:", error);
                document.getElementById('loadingMessage').style.display = 'none';
                const errorMessageDiv = document.getElementById('errorMessage');
                errorMessageDiv.style.display = 'block';
                errorMessageDiv.textContent = `Error loading document: ${error.message}. Please check API key, permissions, or server logs.`;
                // Ensure all relevant UI elements are in the correct error state
                settingsGearContainer.style.display = 'flex'; 
                voiceSelectionControls.style.display = 'none'; 
                updatePlaybackControlVisibility(false, false);
                noVoicesMessage.style.display = 'block'; 
            }
        });
    </script>
</body>
</html>
