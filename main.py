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
import uuid # NEW: For generating unique task IDs for progress tracking

app = Flask(__name__)
CORS(app)

# --- Global dictionary to store synthesis progress ---
# In a production environment, consider a more robust solution like Redis or a database
synthesis_progress = {} # RE-INTRODUCED: Global dictionary for progress tracking

# --- Google Docs API Configuration ---
SCOPES = ['https://www.googleapis.com/auth/documents.readonly']

def get_google_cloud_credentials():
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

                    processed_content = content.replace('\x0b', '<br>') \
                                             .replace('\x85', '<br>') \
                                             .replace('\n', '<br>') 

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

            temp_stripped_content = re.sub(r'<[^>]*>', '', full_paragraph_content).strip()

            if temp_stripped_content == "":
                if '<br>' in full_paragraph_content or '<hr>' in full_paragraph_content:
                    html_content += f"<p>{full_paragraph_content}</p>"
                else:
                    html_content += "<p></p>"
            else:
                html_content += f"<p>{full_paragraph_content.strip()}</p>" 

        elif 'table' in element:
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
        
        document = service.documents().get(documentId=document_id, includeTabsContent=True).execute()

        app.logger.info(f"Document structure fetched. Top-level keys: {list(document.keys())}")

        parsed_data = {
            "title": document.get('title', 'Untitled Document'),
            "document_id": document_id,
            "books": []
        }

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
                        subtitle_text_content = re.sub(r'<[^>]*>', '', element_html_content).strip()

                        if current_chapter and not current_chapter['title']:
                            current_chapter['title'] = subtitle_text_content
                        else:
                            if current_chapter:
                                current_chapter['content'] += element_html_content
                            else:
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
                        if current_chapter:
                            current_chapter['content'] += element_html_content
                        else:
                            if not book_entry['chapters'] and not current_chapter:
                                chapter_counter += 1
                                current_chapter = {
                                    "number": "0", "title": "Introduction", "content": "",
                                    "id": f"chapter-book_entry['id']}-{chapter_counter}"
                                }
                                book_entry['chapters'].append(current_chapter)
                            if current_chapter:
                                current_chapter['content'] += element_html_content

                if current_chapter:
                    book_entry['chapters'].append(current_chapter)

                parsed_data['books'].append(book_entry)
        else:
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
    """Internal helper to synthesize speech with caching and word timings."""
    app.logger.info(f"Synthesizing speech for text: '{text_content[:50]}...' with voice: {voice_name}, lang: {language_code}")
    credentials = get_google_cloud_credentials()
    client = texttospeech.TextToSpeechClient(credentials=credentials)

    synthesis_input = texttospeech.SynthesisInput(text=text_content) 

    voice_params = texttospeech.VoiceSelectionParams(
        language_code=language_code,
        name=voice_name,
    )

    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3
        # Removed enable_word_time_offsets=True as it's not supported by the current library version
    )

    response = client.synthesize_speech(
        input=synthesis_input, voice=voice_params, audio_config=audio_config
    )

    # We can no longer return response.word_timings directly as it's not enabled.
    # The proportional timestamping logic will rely on segment duration.
    return base64.b64encode(response.audio_content).decode('utf-8'), [] # Return empty list for word_timings

# --- NEW LOGIC FOR SPEECH SYNTHESIS INTEGRATION ---

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
                    "text": text # Store original paragraph text
                }]
            })
            
    return synthesis_segments


@app.route('/synthesize-chapter-audio', methods=['POST'])
def synthesize_chapter_audio_endpoint():
    """
    Receives JSON data for a single page, processes it for speech synthesis,
    synthesizes individual audio segments, merges them,
    and returns the merged audio with timestamps for that page.
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
    # Frontend now sends an object with 'chapterParagraphs', 'voiceName', 'languageCode'
    page_paragraphs_from_frontend = data.get('chapterParagraphs') # Renamed for clarity, now represents a single page
    voice_name = data.get('voiceName')
    language_code = data.get('languageCode')

    if not page_paragraphs_from_frontend or not isinstance(page_paragraphs_from_frontend, list):
        return jsonify({"error": "Invalid or empty 'chapterParagraphs' received."}), 400
    if not all([voice_name, language_code]):
        return jsonify({"error": "Missing required parameters: 'voiceName' or 'languageCode'"}), 400

    # Assume all paragraphs belong to the same page, get page number from the first paragraph
    # If no paragraphs, page_num will be None, handled by subsequent checks
    page_num = page_paragraphs_from_frontend[0].get('pageNumber') if page_paragraphs_from_frontend else None

    # RE-INTRODUCED: Generate a unique task ID for this synthesis request
    task_id = str(uuid.uuid4())
    app.logger.info(f"Starting synthesis for page {page_num} with task ID: {task_id}")

    # RE-INTRODUCED: Initialize progress for this task
    synthesis_progress[task_id] = {
        "status": "pending",
        "current_step": 0,
        "total_steps": 0,
        "percent_complete": 0,
        "message": "Initializing synthesis..."
    }

    app.logger.info(f"Received {len(page_paragraphs_from_frontend)} paragraphs for single page synthesis (Page: {page_num}).")
    app.logger.info(f"Requested voice: {voice_name}, language: {language_code}")

    temp_base_dir = None
    try:
        temp_base_dir = tempfile.mkdtemp()
        app.logger.info(f"Created base temporary directory: {temp_base_dir}")

        # The process_paragraphs_for_synthesis is now designed to return one segment per original paragraph
        # (or split a very long single paragraph).
        segments_to_synthesize = process_paragraphs_for_synthesis(page_paragraphs_from_frontend)
        
        if not segments_to_synthesize:
            app.logger.warning(f"No valid text segments found for synthesis on page {page_num}.")
            # Update progress for no text
            synthesis_progress[task_id].update({
                "status": "completed",
                "message": "No text to synthesize for this page.",
                "percent_complete": 100
            })
            return jsonify({
                "pageNumber": page_num,
                "audioContent": None,
                "timestamps": [],
                "error": "No text to synthesize for this page.",
                "taskId": task_id # Return task ID even for empty case
            }), 200 # Return 200 as it's a valid empty response for no text

        individual_audio_segments_pydub = []
        cumulative_segment_timestamps = [] # Store timestamps for all segments on this page

        # Create a temporary directory for this page's audio files
        page_temp_dir = os.path.join(temp_base_dir, f"page_{page_num}")
        os.makedirs(page_temp_dir, exist_ok=True)
        app.logger.info(f"Created temporary directory for page {page_num}: {page_temp_dir}")

        # Define silence duration
        SILENCE_DURATION_MS = 200 # 0.2 seconds

        # RE-INTRODUCED & MODIFIED: Calculate total steps for page 1 based on the number of *synthesis segments* + 1 for merging
        # Now, each synthesis segment largely corresponds to an original paragraph (or a part of a very long one).
        # This will provide more granular updates.
        if page_num == 1: # Only track progress for the first page synthesis
            synthesis_progress[task_id]["total_steps"] = len(segments_to_synthesize) + 1 # +1 for the merge step
            synthesis_progress[task_id]["message"] = "Starting audio synthesis..."
            synthesis_progress[task_id]["status"] = "in_progress"

        # Perform speech synthesis for each segment and collect pydub objects
        current_page_audio_offset_ms = 0 # Tracks the cumulative time for timestamps on this page
        for i, segment in enumerate(segments_to_synthesize):
            segment_text = segment['text']
            
            if not segment_text.strip():
                app.logger.warning(f"Skipping synthesis for empty text segment {i} on page {page_num}.")
                continue

            audio_base64, _ = _synthesize_speech_cached(segment_text, voice_name, language_code) 
            audio_content_bytes = base64.b64decode(audio_base64)
            
            audio_segment_pydub = AudioSegment.from_file(io.BytesIO(audio_content_bytes), format="mp3")
            individual_audio_segments_pydub.append(audio_segment_pydub)

            # RE-INTRODUCED & MODIFIED: Update progress for page 1 after each segment is synthesized
            if page_num == 1:
                synthesis_progress[task_id]["current_step"] = i + 1 # Increment for each *synthesis segment* completed
                synthesis_progress[task_id]["percent_complete"] = int((synthesis_progress[task_id]["current_step"] / synthesis_progress[task_id]["total_steps"]) * 100)
                synthesis_progress[task_id]["message"] = f"Synthesizing segment {i+1} of {len(segments_to_synthesize)}..."
                app.logger.info(f"Progress for task {task_id}: {synthesis_progress[task_id]['percent_complete']}%")


            # Generate timestamps for the original paragraphs within this *segment*
            # This is the proportionally distributed timestamping.
            # Since each segment now largely corresponds to one original paragraph,
            # this part will be simpler, directly mapping the segment's audio to its single original paragraph.
            segment_duration_ms = audio_segment_pydub.duration_seconds * 1000
            
            # Assuming original_paragraphs_meta will typically have only one entry now
            for p_meta in segment["original_paragraphs_meta"]:
                cumulative_segment_timestamps.append({
                    "pageNumber": p_meta['pageNumber'],
                    "paragraphIndexOnPage": p_meta['paragraphIndexOnPage'],
                    "start_time_ms": int(current_page_audio_offset_ms), # Start of this segment
                    "end_time_ms": int(current_page_audio_offset_ms + segment_duration_ms) # End of this segment
                })
            
            current_page_audio_offset_ms += segment_duration_ms

            # Add silence after each segment, except the last one
            if i < len(segments_to_synthesize) - 1:
                # Create a silent segment
                silence_segment = AudioSegment.silent(duration=SILENCE_DURATION_MS, frame_rate=audio_segment_pydub.frame_rate)
                individual_audio_segments_pydub.append(silence_segment)
                current_page_audio_offset_ms += SILENCE_DURATION_MS # Account for silence in offset


        if not individual_audio_segments_pydub:
            app.logger.warning(f"No audio segments generated for page {page_num}.")
            # Update progress for no audio
            synthesis_progress[task_id].update({
                "status": "completed",
                "message": "No audio generated for this page.",
                "percent_complete": 100
            })
            return jsonify({
                "pageNumber": page_num,
                "audioContent": None,
                "timestamps": [],
                "error": "No audio generated for this page.",
                "taskId": task_id
            }), 200 # Return 200 as it's a valid empty response for no audio

        # Merge audio files using pydub
        merged_audio = AudioSegment.empty()
        for seg in individual_audio_segments_pydub:
            merged_audio += seg

        # RE-INTRODUCED & MODIFIED: Update progress for page 1 during merge step
        if page_num == 1:
            synthesis_progress[task_id]["current_step"] = synthesis_progress[task_id]["total_steps"] # Set to last step
            synthesis_progress[task_id]["percent_complete"] = 100
            synthesis_progress[task_id]["message"] = "Merging audio segments..."
            app.logger.info(f"Progress for task {task_id}: {synthesis_progress[task_id]['percent_complete']}%")

        # Export the merged audio to a temporary file
        merged_audio_filename = f"merged_page_{page_num}.mp3"
        merged_audio_path = os.path.join(page_temp_dir, merged_audio_filename)
        merged_audio.export(merged_audio_path, format="mp3")
        app.logger.info(f"Merged audio for page {page_num} saved to: {merged_audio_path}")

        # Read the merged audio file and encode it to base64
        with open(merged_audio_path, 'rb') as f:
            merged_audio_content = f.read()
        
        merged_audio_base64 = base64.b64encode(merged_audio_content).decode('utf-8')

        # RE-INTRODUCED: Final progress update for completion
        synthesis_progress[task_id].update({
            "status": "completed",
            "message": f"Audio synthesized and merged for page {page_num}.",
            "percent_complete": 100
        })

        # Return a single object for the page's audio response
        return jsonify({
            "success": True,
            "pageNumber": page_num,
            "audioContent": merged_audio_base64,
            "format": "audio/mpeg",
            "timestamps": cumulative_segment_timestamps,
            "message": f"Audio synthesized and merged for page {page_num}.",
            "taskId": task_id # RE-INTRODUCED: Include the task ID in the final response
        })

    except Exception as e:
        app.logger.error(f"An error occurred during single page audio synthesis: {e}", exc_info=True)
        # Update progress for failure
        synthesis_progress[task_id].update({
            "status": "failed",
            "message": f"An error occurred: {str(e)}",
            "percent_complete": 0
        })
        return jsonify({"error": f"An unexpected server error occurred: {str(e)}"}), 500
    finally:
        # Clean up the base temporary directory and its contents
        if temp_base_dir and os.path.exists(temp_base_dir):
            shutil.rmtree(temp_base_dir)
            app.logger.info(f"Cleaned up base temporary directory: {temp_base_dir}")
        # RE-INTRODUCED: Clean up the synthesis_progress entry
        if task_id in synthesis_progress:
            del synthesis_progress[task_id]
            app.logger.info(f"Cleaned up synthesis_progress entry for task ID: {task_id}")


# RE-INTRODUCED: NEW ENDPOINT TO GET SYNTHESIS PROGRESS ---
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
        return jsonify(progress)
    else:
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
