import os
import json
from flask import Flask, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from flask_cors import CORS
import re
import requests
from bs4 import BeautifulSoup # Import BeautifulSoup for robust HTML parsing

# NEW IMPORTS FOR TEXT-TO-SPEECH
from google.cloud import texttospeech
import base64
from functools import lru_cache # Import lru_cache for caching

# NEW IMPORT for pydub
from pydub import AudioSegment
import io # For handling in-memory bytes as files
import tempfile # For creating temporary files and directories
import shutil # For cleaning up temporary directories
import math # For math.isclose for float comparisons
import uuid # For generating unique task IDs for progress tracking
import threading # NEW: For running synthesis in a background thread

app = Flask(__name__)
CORS(app)

# --- Global dictionary to store synthesis progress ---
# In a production environment, consider a more robust solution like Redis or a database
# This dictionary will hold the status, percentage, message, and eventually the audio content
synthesis_progress = {}

# --- Google Docs API Configuration ---
SCOPES = ['https://www.googleapis.com/auth/documents.readonly']

def get_google_cloud_credentials():
    """Retrieves Google Cloud credentials from environment variables."""
    try:
        creds_json = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON')
        if not creds_json:
            app.logger.error("GOOGLE_APPLICATION_CREDENTIALS_JSON environment variable not set.")
            raise ValueError("GOOGLE_APPLICATION_CREDENTIALS_JSON environment variable not set.")

        info = json.loads(creds_json)
        return service_account.Credentials.from_service_account_info(info)
    except Exception as e:
        app.logger.error(f"Error loading Google Cloud credentials: {e}", exc_info=True)
        raise

def get_docs_service():
    """Initializes and returns a Google Docs API service client."""
    try:
        credentials = get_google_cloud_credentials()
        service = build('docs', 'v1', credentials=credentials)
        app.logger.info("Google Docs service initialized successfully.")
        return service
    except Exception as e:
        app.logger.error(f"Error initializing Google Docs service: {e}", exc_info=True)
        raise

def extract_formatted_html_from_elements(elements):
    """
    Extracts and formats HTML content from Google Docs API elements.
    Handles paragraphs, text styles (bold, italic, underline), and horizontal rules.
    """
    html_content = ""
    if not elements:
        return html_content

    for element in elements:
        if 'paragraph' in element:
            paragraph_html_parts = []
            for text_run in element['paragraph']['elements']:
                if 'textRun' in text_run:
                    content = text_run['textRun']['content']
                    text_style = text_run['textRun'].get('textStyle', {})

                    # Replace special characters with HTML breaks
                    processed_content = content.replace('\x0b', '<br>') \
                                             .replace('\x85', '<br>') \
                                             .replace('\n', '<br>') 

                    # Apply text styling
                    if text_style.get('bold'):
                        processed_content = f"<strong>{processed_content}</strong>"
                    if text_style.get('italic'):
                        processed_content = f"<em>{processed_content}</em>"
                    if text_style.get('underline'):
                        processed_content = f"<u>{processed_content}</u>"
                    
                    paragraph_html_parts.append(processed_content)

                elif 'horizontalRule' in text_run:
                    paragraph_html_parts.append("<hr>")
            
            full_paragraph_content = "".join(paragraph_html_parts)

            # Check if the paragraph is empty after stripping HTML tags
            temp_stripped_content = re.sub(r'<[^>]*>', '', full_paragraph_content).strip()

            if temp_stripped_content == "":
                # If it contains only breaks or HR, keep it as a paragraph
                if '<br>' in full_paragraph_content or '<hr>' in full_paragraph_content:
                    html_content += f"<p>{full_paragraph_content}</p>"
                else:
                    html_content += "<p></p>" # Empty paragraph
            else:
                html_content += f"<p>{full_paragraph_content.strip()}</p>" 

        elif 'table' in element:
            # Basic table handling
            table_html = "<table>"
            for row in element['table']['tableRows']:
                table_html += "<tr>"
                for cell in row['tableCells']:
                    table_html += f"<td>{extract_formatted_html_from_elements(cell['content'])}</td>"
                table_html += "</tr>"
            table_html += "</table>"
            html_content += table_html + "\n"
            
    return html_content

# --- API Endpoint to Fetch Document Content ---
@app.route('/get-doc-content', methods=['GET'])
def get_document_content():
    """
    Fetches content from a specified Google Document ID, parses it into books and chapters,
    and returns it as JSON.
    """
    # --- AUTHENTICATION CHECK ---
    expected_api_key = os.environ.get('RAILWAY_APP_API_KEY')
    incoming_api_key = request.headers.get('X-API-Key')

    if not expected_api_key:
        app.logger.critical("RAILWAY_APP_API_KEY environment variable is not set in Railway!")
        return jsonify({"error": "Server configuration error: API key not set."}), 500

    if not incoming_api_key or incoming_api_key != expected_api_key:
        app.logger.warning(f"Unauthorized access attempt. Incoming key: '{incoming_api_key}'")
        return jsonify({"error": "Unauthorized access. Invalid API Key."}), 401
    # --- END AUTHENTICATION CHECK ---

    document_id = '1ubt637f0K87_Och3Pin9GbJM7w6wzf3M2RCmHbmHgYI' # Confirmed correct ID

    try:
        service = get_docs_service()
        app.logger.info(f"Fetching document structure with ID: {document_id}")
        
        # Fetch the document including tabs content
        document = service.documents().get(documentId=document_id, includeTabsContent=True).execute()

        app.logger.info(f"Document structure fetched. Top-level keys: {list(document.keys())}")

        parsed_data = {
            "title": document.get('title', 'Untitled Document'),
            "document_id": document_id,
            "books": []
        }

        # Process content from tabs if available
        if 'tabs' in document and document['tabs']:
            for i, tab_data in enumerate(document['tabs']):
                tab_properties = tab_data.get('tabProperties', {})
                document_tab = tab_data.get('documentTab', {})
                tab_body = document_tab.get('body', {})
                tab_content_elements = tab_body.get('content', [])

                book_entry = {
                    "title": tab_properties.get('title', f"Tab {i+1}"),
                    "id": f"tab-{tab_properties.get('tabId', f'tab_{i+1}').replace('.', '_')}",
                    "chapters": []
                }

                current_chapter = None
                chapter_counter = 0

                for element in tab_content_elements:
                    named_style_type = None
                    if 'paragraph' in element:
                        named_style_type = element['paragraph'].get('paragraphStyle', {}).get('namedStyleType')

                    element_html_content = extract_formatted_html_from_elements([element])

                    if named_style_type == 'HEADING_1':
                        # New chapter starts with HEADING_1
                        if current_chapter:
                            book_entry['chapters'].append(current_chapter)
                        chapter_counter += 1
                        chapter_text_content = re.sub(r'<[^>]*>', '', element_html_content).strip()

                        current_chapter = {
                            "number": chapter_text_content,
                            "title": "",
                            "content": "",
                            "id": f"chapter-{book_entry['id']}-{chapter_counter}"
                        }
                    elif named_style_type == 'SUBTITLE':
                        # Subtitle is the chapter title
                        subtitle_text_content = re.sub(r'<[^>]*>', '', element_html_content).strip()

                        if current_chapter and not current_chapter['title']:
                            current_chapter['title'] = subtitle_text_content
                        else:
                            # If no current chapter or title already set, treat as regular content
                            if current_chapter:
                                current_chapter['content'] += element_html_content
                            else:
                                # Handle case where SUBTITLE appears before any HEADING_1 (e.g., intro)
                                if not book_entry['chapters'] and not current_chapter:
                                    chapter_counter += 1
                                    current_chapter = {
                                        "number": "0", "title": "Introduction", "content": "",
                                        "id": f"chapter-{book_entry['id']}-{chapter_counter}"
                                    }
                                    book_entry['chapters'].append(current_chapter)
                                if current_chapter:
                                    current_chapter['content'] += element_html_content
                    else:
                        # Regular paragraph content
                        if current_chapter:
                            current_chapter['content'] += element_html_content
                        else:
                            # If content appears before any HEADING_1 or SUBTITLE, treat as intro
                            if not book_entry['chapters'] and not current_chapter:
                                chapter_counter += 1
                                current_chapter = {
                                    "number": "0", "title": "Introduction", "content": "",
                                    "id": f"chapter-{book_entry['id']}-{chapter_counter}" # Corrected this line
                                }
                                book_entry['chapters'].append(current_chapter)
                            if current_chapter:
                                current_chapter['content'] += element_html_content

                if current_chapter:
                    book_entry['chapters'].append(current_chapter)

                parsed_data['books'].append(book_entry)
        else:
            # Fallback for documents without tabs (single main body)
            app.logger.warning("No 'tabs' found in document response. Assuming single main body.")
            main_body_content_elements = document.get('body', {}).get('content', [])
            
            single_book_entry = {
                "title": document.get('title', 'Main Document'),
                "id": "book-main",
                "chapters": []
            }

            current_chapter = None
            chapter_counter = 0

            for element in main_body_content_elements:
                named_style_type = None
                if 'paragraph' in element:
                    named_style_type = element['paragraph'].get('paragraphStyle', {}).get('namedStyleType')
                    
                element_html_content = extract_formatted_html_from_elements([element])

                if named_style_type == 'HEADING_1':
                    if current_chapter:
                        single_book_entry['chapters'].append(current_chapter)
                    chapter_counter += 1
                    chapter_text_content = re.sub(r'<[^>]*>', '', element_html_content).strip()
                    current_chapter = {
                        "number": chapter_text_content,
                        "title": "",
                        "content": "",
                        "id": f"chapter-main-{chapter_counter}"
                    }
                elif named_style_type == 'SUBTITLE':
                    subtitle_text_content = re.sub(r'<[^>]*>', '', element_html_content).strip()
                    if current_chapter and not current_chapter['title']:
                        current_chapter['title'] = subtitle_text_content
                    else:
                        if current_chapter:
                            current_chapter['content'] += element_html_content
                        else:
                            if not single_book_entry['chapters'] and not current_chapter:
                                chapter_counter += 1
                                current_chapter = {
                                    "number": "0", "title": "Introduction", "content": "",
                                    "id": f"chapter-main-{chapter_counter}"
                                }
                                single_book_entry['chapters'].append(current_chapter)
                            if current_chapter:
                                current_chapter['content'] += element_html_content
                else:
                    if current_chapter:
                        current_chapter['content'] += element_html_content
                    else:
                        if not single_book_entry['chapters'] and not current_chapter:
                            chapter_counter += 1
                            current_chapter = {
                                "number": "0", "title": "Introduction", "content": "",
                                "id": f"chapter-main-{chapter_counter}"
                            }
                            single_book_entry['chapters'].append(current_chapter)
                        if current_chapter:
                            current_chapter['content'] += element_html_content

            if current_chapter:
                single_book_entry['chapters'].append(current_chapter)

            parsed_data['books'].append(single_book_entry)

        # Filter out books that ended up with no chapters
        parsed_data['books'] = [book for book in parsed_data['books'] if book['chapters']]

        return jsonify(parsed_data)

    except HttpError as e:
        app.logger.error(f"Google API Error: {e.status_code} - {e.reason}", exc_info=True)
        return jsonify({"error": f"Google API Error: {e.reason}", "code": e.status_code}), e.status_code
    except ValueError as e:
        app.logger.error(f"Configuration Error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    except KeyError as e:
        app.logger.error(f"Data parsing error: Missing expected key {e} in Google Doc response. Check document permissions or structure.", exc_info=True)
        return jsonify({"error": f"Data parsing error: Missing expected key {e} in Google Doc response. Possible permissions issue or empty document."}), 500
    except Exception as e:
        app.logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        return jsonify({"error": f"An unexpected server error occurred: {str(e)}"}), 500


# Use lru_cache to cache the synthesis results. Max size can be adjusted.
@lru_cache(maxsize=128) # Cache up to 128 unique speech synthesis results. Adjust as needed.
def _synthesize_speech_cached(text_content, voice_name, language_code):
    """Internal helper to synthesize speech with caching."""
    app.logger.info(f"Synthesizing speech for text: '{text_content[:50]}...' with voice: {voice_name}, lang: {language_code}")
    credentials = get_google_cloud_credentials()
    client = texttospeech.TextToSpeechClient(credentials=credentials)

    synthesis_input = texttospeech.SynthesisInput(text=text_content) 

    voice_params = texttospeech.VoiceSelectionParams(
        language_code=language_code,
        name=voice_name,
    )

    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        enable_time_pings=True # Re-enabling time pings for word timings
    )

    response = client.synthesize_speech(
        input=synthesis_input, voice=voice_params, audio_config=audio_config
    )

    # Extract word timings
    word_timings = []
    for word_timing in response.time_pings:
        word_timings.append({
            "word": word_timing.text,
            "start_time_ms": word_timing.start_time.seconds * 1000 + word_timing.start_time.nanos // 1_000_000,
            "end_time_ms": word_timing.end_time.seconds * 1000 + word_timing.end_time.nanos // 1_000_000
        })

    return base64.b64encode(response.audio_content).decode('utf-8'), word_timings

# This constant will now be used primarily to split *individual* very long paragraphs,
# ensuring each original paragraph (or its split parts) becomes a synthesis segment.
MAX_CHAR_COUNT_FOR_NARRATION = 768 

def process_paragraphs_for_synthesis(paragraphs_data):
    """
    Processes the incoming paragraphs (from frontend JSON) to create a new list of segments
    for speech synthesis. This revised version ensures that each original paragraph (or a
    split part of a very long one) forms its own segment for individual synthesis.
    """
    synthesis_segments = []

    for paragraph in paragraphs_data:
        text = paragraph.get('text', '').strip()
        paragraph_type = paragraph.get('paragraphType', 'narration') # Use 'paragraphType' from frontend
        original_page_number = paragraph.get('pageNumber')
        original_paragraph_index_on_page = paragraph.get('paragraphIndexOnPage')

        # Skip empty paragraphs after stripping
        if not text:
            continue

        # If a single paragraph is extremely long, it might need to be split.
        # This ensures that no single API call exceeds character limits.
        # For typical paragraphs, this means each original paragraph becomes one segment.
        if len(text) > MAX_CHAR_COUNT_FOR_NARRATION:
            # Break down long paragraphs into smaller chunks
            # This simple split might break words, but it ensures API limits are met.
            # For more sophisticated splitting (e.g., by sentence), a more advanced NLP library would be needed.
            chunks = [text[i:i + MAX_CHAR_COUNT_FOR_NARRATION] for i in range(0, len(text), MAX_CHAR_COUNT_FOR_NARRATION)]
            for j, chunk in enumerate(chunks):
                synthesis_segments.append({
                    "text": chunk,
                    "type": paragraph_type, # Retain original type
                    "original_paragraphs_meta": [{ # Link back to the single original paragraph
                        "pageNumber": original_page_number,
                        "paragraphIndexOnPage": original_paragraph_index_on_page,
                        "chunk_index": j, # Add chunk index for debugging/tracking
                        "text": chunk # Store the chunk text for proportional timestamping within the chunk
                    }]
                })
        else:
            # For paragraphs within the limit, each becomes its own synthesis segment
            synthesis_segments.append({
                "text": text,
                "type": paragraph_type,
                "original_paragraphs_meta": [{
                    "pageNumber": original_page_number,
                    "paragraphIndexOnPage": original_paragraph_index_on_page,
                    "chunk_index": 0, # Only one chunk
                    "text": text # Store original paragraph text
                }]
            })
            
    return synthesis_segments

def _synthesize_and_process_page_audio(task_id, page_paragraphs_from_frontend, voice_name, language_code, page_num):
    """
    Performs the actual speech synthesis and audio merging in a background thread.
    Updates the global synthesis_progress dictionary.
    """
    temp_base_dir = None
    try:
        temp_base_dir = tempfile.mkdtemp()
        app.logger.info(f"Task {task_id}: Created base temporary directory: {temp_base_dir}")

        segments_to_synthesize = process_paragraphs_for_synthesis(page_paragraphs_from_frontend)
        
        if not segments_to_synthesize:
            app.logger.warning(f"Task {task_id}: No valid text segments found for synthesis on page {page_num}.")
            synthesis_progress[task_id].update({
                "status": "completed",
                "message": "No text to synthesize for this page.",
                "percent_complete": 100
            })
            return # Exit background task

        individual_audio_segments_pydub = []
        cumulative_segment_timestamps = [] # Store timestamps for all segments on this page

        page_temp_dir = os.path.join(temp_base_dir, f"page_{page_num}")
        os.makedirs(page_temp_dir, exist_ok=True)
        app.logger.info(f"Task {task_id}: Created temporary directory for page {page_num}: {page_temp_dir}")

        SILENCE_DURATION_MS = 200 # 0.2 seconds

        total_segments = len(segments_to_synthesize)
        synthesis_progress[task_id]["total_steps"] = total_segments + 1 # +1 for the merge step
        synthesis_progress[task_id]["message"] = "Starting audio synthesis..."
        synthesis_progress[task_id]["status"] = "in_progress"

        current_page_audio_offset_ms = 0 # Tracks the cumulative time for timestamps on this page
        for i, segment in enumerate(segments_to_synthesize):
            segment_text = segment['text']
            
            if not segment_text.strip():
                app.logger.warning(f"Task {task_id}: Skipping synthesis for empty text segment {i} on page {page_num}.")
                continue

            audio_base664, word_timings = _synthesize_speech_cached(segment_text, voice_name, language_code) 
            audio_content_bytes = base64.b64decode(audio_base664)
            
            audio_segment_pydub = AudioSegment.from_file(io.BytesIO(audio_content_bytes), format="mp3")
            individual_audio_segments_pydub.append(audio_segment_pydub)

            # Update progress after each segment is synthesized
            synthesis_progress[task_id]["current_step"] = i + 1
            synthesis_progress[task_id]["percent_complete"] = int((synthesis_progress[task_id]["current_step"] / synthesis_progress[task_id]["total_steps"]) * 100)
            synthesis_progress[task_id]["message"] = f"Synthesizing segment {i+1} of {total_segments}..."
            app.logger.info(f"Task {task_id}: Progress {synthesis_progress[task_id]['percent_complete']}%")

            # Generate timestamps for the original paragraphs within this *segment*
            # If word_timings are available, use them. Otherwise, use proportional timing.
            segment_duration_ms = audio_segment_pydub.duration_seconds * 1000

            if word_timings:
                # Adjust word timings to be relative to the start of the current page's overall audio
                for wt in word_timings:
                    cumulative_segment_timestamps.append({
                        "pageNumber": page_num,
                        "paragraphIndexOnPage": segment["original_paragraphs_meta"][0]["paragraphIndexOnPage"], # Assuming one original paragraph per segment
                        "start_time_ms": int(current_page_audio_offset_ms + wt["start_time_ms"]),
                        "end_time_ms": int(current_page_audio_offset_ms + wt["end_time_ms"])
                    })
            else:
                # Fallback to proportional timestamping if word timings are not available
                # This assumes the entire segment corresponds to a single logical paragraph for highlighting
                for p_meta in segment["original_paragraphs_meta"]:
                    cumulative_segment_timestamps.append({
                        "pageNumber": p_meta['pageNumber'],
                        "paragraphIndexOnPage": p_meta['paragraphIndexOnPage'],
                        "start_time_ms": int(current_page_audio_offset_ms),
                        "end_time_ms": int(current_page_audio_offset_ms + segment_duration_ms)
                    })
            
            current_page_audio_offset_ms += segment_duration_ms

            # Add silence after each segment, except the last one
            if i < total_segments - 1:
                silence_segment = AudioSegment.silent(duration=SILENCE_DURATION_MS, frame_rate=audio_segment_pydub.frame_rate)
                individual_audio_segments_pydub.append(silence_segment)
                current_page_audio_offset_ms += SILENCE_DURATION_MS # Account for silence in offset


        if not individual_audio_segments_pydub:
            app.logger.warning(f"Task {task_id}: No audio segments generated for page {page_num}.")
            synthesis_progress[task_id].update({
                "status": "completed",
                "message": "No audio generated for this page.",
                "percent_complete": 100
            })
            return # Exit background task

        # Merge audio files using pydub
        merged_audio = AudioSegment.empty()
        for seg in individual_audio_segments_pydub:
            merged_audio += seg

        # Update progress for merge step
        synthesis_progress[task_id]["current_step"] = synthesis_progress[task_id]["total_steps"]
        synthesis_progress[task_id]["percent_complete"] = 100
        synthesis_progress[task_id]["message"] = "Merging audio segments..."
        app.logger.info(f"Task {task_id}: Progress {synthesis_progress[task_id]['percent_complete']}%")

        # Export the merged audio to a temporary file
        merged_audio_filename = f"merged_page_{page_num}.mp3"
        merged_audio_path = os.path.join(page_temp_dir, merged_audio_filename)
        merged_audio.export(merged_audio_path, format="mp3")
        app.logger.info(f"Task {task_id}: Merged audio for page {page_num} saved to: {merged_audio_path}")

        # Read the merged audio file and encode it to base64
        with open(merged_audio_path, 'rb') as f:
            merged_audio_content = f.read()
        
        merged_audio_base64 = base64.b64encode(merged_audio_content).decode('utf-8')

        # Final progress update for completion
        synthesis_progress[task_id].update({
            "status": "completed",
            "message": f"Audio synthesized and merged for page {page_num}.",
            "percent_complete": 100,
            "audioContent": merged_audio_base64,
            "format": "audio/mpeg",
            "timestamps": cumulative_segment_timestamps,
            "pageNumber": page_num # Include page number in the final result
        })
        app.logger.info(f"Task {task_id}: Synthesis completed for page {page_num}.")

    except Exception as e:
        app.logger.error(f"Task {task_id}: An error occurred during single page audio synthesis: {e}", exc_info=True)
        # Update progress for failure
        synthesis_progress[task_id].update({
            "status": "failed",
            "message": f"An error occurred: {str(e)}",
            "percent_complete": synthesis_progress[task_id].get("percent_complete", 0) # Keep last known progress
        })
    finally:
        # Clean up the base temporary directory and its contents
        if temp_base_dir and os.path.exists(temp_base_dir):
            shutil.rmtree(temp_base_dir)
            app.logger.info(f"Task {task_id}: Cleaned up base temporary directory: {temp_base_dir}")
        # IMPORTANT: Do NOT delete from synthesis_progress here. The frontend needs to fetch the completed audio.
        # Cleanup of synthesis_progress entries should happen after a timeout or when the frontend explicitly indicates it's done.


@app.route('/synthesize-chapter-audio', methods=['POST'])
def synthesize_chapter_audio_endpoint():
    """
    Receives JSON data for a single page, initiates speech synthesis in a background thread,
    and immediately returns a task ID for progress polling.
    """
    # --- AUTHENTICATION CHECK ---
    expected_api_key = os.environ.get('RAILWAY_APP_API_KEY')
    incoming_api_key = request.headers.get('X-API-Key')

    if not expected_api_key or not incoming_api_key or incoming_api_key != expected_api_key:
        app.logger.warning(f"Unauthorized access attempt. Incoming key: '{incoming_api_key}'")
        return jsonify({"error": "Unauthorized access. Invalid API Key."}), 401
    # --- END AUTHENTICATION CHECK ---

    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    page_paragraphs_from_frontend = data.get('chapterParagraphs')
    voice_name = data.get('voiceName')
    language_code = data.get('languageCode')

    if not page_paragraphs_from_frontend or not isinstance(page_paragraphs_from_frontend, list):
        return jsonify({"error": "Invalid or empty 'chapterParagraphs' received."}), 400
    if not all([voice_name, language_code]):
        return jsonify({"error": "Missing required parameters: 'voiceName' or 'languageCode'"}), 400

    page_num = page_paragraphs_from_frontend[0].get('pageNumber') if page_paragraphs_from_frontend else None
    
    task_id = str(uuid.uuid4())
    app.logger.info(f"Received synthesis request for page {page_num}. Assigning task ID: {task_id}")

    # Initialize progress for this task immediately
    synthesis_progress[task_id] = {
        "status": "accepted",
        "percent_complete": 0,
        "message": "Synthesis request accepted, starting processing..."
    }

    # Start the synthesis in a background thread
    thread = threading.Thread(
        target=_synthesize_and_process_page_audio, 
        args=(task_id, page_paragraphs_from_frontend, voice_name, language_code, page_num)
    )
    thread.daemon = True # Allow the main program to exit even if thread is running
    thread.start()

    # Immediately return the task ID so the frontend can start polling
    return jsonify({"taskId": task_id, "status": "accepted", "message": "Synthesis initiated. You can poll for progress."}), 202


# --- NEW ENDPOINT TO GET SYNTHESIS PROGRESS ---
@app.route('/get-synthesis-progress/<task_id>', methods=['GET'])
def get_synthesis_progress(task_id):
    """
    API endpoint to fetch the current progress of a speech synthesis task.
    """
    # --- AUTHENTICATION CHECK ---
    expected_api_key = os.environ.get('RAILWAY_APP_API_KEY')
    incoming_api_key = request.headers.get('X-API-Key')

    if not expected_api_key or not incoming_api_key or incoming_api_key != expected_api_key:
        app.logger.warning(f"Unauthorized access attempt. Incoming key: '{incoming_api_key}' for task {task_id}")
        return jsonify({"error": "Unauthorized access. Invalid API Key."}), 401
    # --- END AUTHENTICATION CHECK ---

    progress = synthesis_progress.get(task_id)
    if progress:
        # If the task is completed, return the full progress data including audioContent
        if progress.get("status") == "completed":
            return jsonify(progress)
        else:
            # For ongoing tasks, return only the progress status, percentage, and message
            return jsonify({
                "status": progress.get("status", "unknown"),
                "percent_complete": progress.get("percent_complete", 0),
                "message": progress.get("message", "Processing...")
            })
    else:
        # Task not found or already cleaned up
        return jsonify({"status": "not_found", "message": "Task ID not found or expired."}), 404

# --- Existing /get-google-tts-voices endpoint ---
@app.route('/get-google-tts-voices', methods=['GET'])
def get_google_tts_voices_endpoint():
    """
    API endpoint to fetch available Google TTS voices using a Google API Key from environment variables.
    This acts as a proxy for the Google Text-to-Speech v1/voices endpoint.
    """
    google_api_key = os.environ.get('google_api')

    if not google_api_key:
        app.logger.error("The 'google_api' environment variable is not set.")
        return jsonify({"error": "Server configuration error: Google API key not set for voice listing."}), 500

    try:
        google_tts_voices_api_url = f"https://texttospeech.googleapis.com/v1/voices?key={google_api_key}"
        response = requests.get(google_tts_voices_api_url)
        response.raise_for_status()
        
        return jsonify(response.json())
        
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error fetching Google TTS voices: {e}", exc_info=True)
        return jsonify({"error": f"Failed to fetch Google TTS voices: {str(e)}"}), 500
    except Exception as e:
        app.logger.error(f"An unexpected error occurred while fetching voices: {e}", exc_info=True)
        return jsonify({"error": f"An unexpected server error occurred: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
