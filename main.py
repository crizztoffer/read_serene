import os
import json
from flask import Flask, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from flask_cors import CORS
import re
import requests
from bs4 import BeautifulSoup

# NEW IMPORTS FOR TEXT-TO-SPEECH
from google.cloud import texttospeech
import base64
from functools import lru_cache

# NEW IMPORT for pydub
from pydub import AudioSegment
import tempfile # For creating temporary files and directories
import shutil # For cleaning up temporary directories

app = Flask(__name__)
CORS(app)

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
                                    "id": f"chapter-{book_entry['id']}-{chapter_counter}"
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
        return jsonify({"error": f"An unexpected server error occurred: {e}"}), 500


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
        enable_word_time_offsets=True # Enable word timing offsets for timestamp generation
    )

    response = client.synthesize_speech(
        input=synthesis_input, voice=voice_params, audio_config=audio_config
    )

    audio_base64 = base64.b64encode(response.audio_content).decode('utf-8')
    return audio_base64, response.word_timings # Return word timings along with audio

# --- NEW LOGIC FOR SPEECH SYNTHESIS INTEGRATION ---

MAX_CHAR_COUNT_FOR_NARRATION = 768 # Define max character count for appending narration type paragraphs

def process_paragraphs_for_synthesis(paragraphs_data):
    """
    Processes the incoming paragraphs (from frontend JSON) to create a new list of segments
    optimized for speech synthesis, applying concatenation rules based on paragraph type.
    Each segment will also include the original paragraph indices it covers.
    """
    synthesis_segments = []
    current_narration_buffer = []
    current_narration_char_count = 0
    current_narration_indices = []

    for paragraph in paragraphs_data:
        text = paragraph.get('text', '').strip()
        paragraph_type = paragraph.get('paragraph_type', 'narration') # Default to narration
        original_page_number = paragraph.get('pageNumber')
        original_paragraph_index_on_page = paragraph.get('paragraphIndexOnPage')

        # Skip empty paragraphs after stripping
        if not text:
            continue

        if paragraph_type == 'narration':
            # Check if adding this narration paragraph exceeds the limit
            # Add 1 for the space that will be used to join paragraphs if the buffer is not empty
            potential_new_char_count = current_narration_char_count + len(text) + (1 if current_narration_buffer else 0)
            
            if current_narration_buffer and potential_new_char_count > MAX_CHAR_COUNT_FOR_NARRATION:
                # If buffer exists and new text exceeds limit, finalize the current buffer
                synthesis_segments.append({
                    "text": " ".join(current_narration_buffer),
                    "type": "narration",
                    "original_paragraphs": current_narration_indices
                })
                # Start a new buffer with the current paragraph
                current_narration_buffer = [text]
                current_narration_char_count = len(text)
                current_narration_indices = [{
                    "pageNumber": original_page_number,
                    "paragraphIndexOnPage": original_paragraph_index_on_page
                }]
            else:
                # Append to current buffer
                current_narration_buffer.append(text)
                current_narration_char_count = potential_new_char_count
                current_narration_indices.append({
                    "pageNumber": original_page_number,
                    "paragraphIndexOnPage": original_paragraph_index_on_page
                })

        else: # Dialogue or Italicized type
            # If there's an active narration buffer, finalize it before adding non-narration
            if current_narration_buffer:
                synthesis_segments.append({
                    "text": " ".join(current_narration_buffer),
                    "type": "narration",
                    "original_paragraphs": current_narration_indices
                })
                current_narration_buffer = []
                current_narration_char_count = 0
                current_narration_indices = []
            
            # Add dialogue or italicized paragraph individually
            synthesis_segments.append({
                "text": text,
                "type": paragraph_type,
                "original_paragraphs": [{
                    "pageNumber": original_page_number,
                    "paragraphIndexOnPage": original_paragraph_index_on_page
                }]
            })

    # After loop, if any narration buffer remains, add it to segments
    if current_narration_buffer:
        synthesis_segments.append({
            "text": " ".join(current_narration_buffer),
            "type": "narration",
            "original_paragraphs": current_narration_indices
        })
    return synthesis_segments

@app.route('/synthesize-chapter-audio', methods=['POST'])
def synthesize_chapter_audio_endpoint():
    """
    Receives JSON data for a chapter (multiple pages), processes it for speech synthesis,
    synthesizes individual audio segments, merges them per page using pydub,
    and returns the merged audio for each page.
    """
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    # The frontend is sending an array of paragraphs from the current chapter,
    # which includes pageNumber, paragraphIndexOnPage, paragraphType, and text.
    chapter_paragraphs_from_frontend = data 
    
    # Assuming a default voice and language for now. You might want to pass these from frontend.
    voice_name = "en-US-Wavenet-D" # Example voice, adjust as needed
    language_code = "en-US" # Example language, adjust as needed

    if not chapter_paragraphs_from_frontend or not isinstance(chapter_paragraphs_from_frontend, list):
        return jsonify({"error": "Invalid or empty chapter paragraphs received."}), 400

    app.logger.info(f"Received {len(chapter_paragraphs_from_frontend)} paragraphs for chapter synthesis.")

    # Group paragraphs by page number
    paragraphs_by_page = {}
    for p in chapter_paragraphs_from_frontend:
        page_num = p.get('pageNumber')
        if page_num not in paragraphs_by_page:
            paragraphs_by_page[page_num] = []
        paragraphs_by_page[page_num].append(p)
    
    sorted_page_numbers = sorted(paragraphs_by_page.keys())
    
    # Prepare responses for each page
    page_audio_responses = []

    # Implement page-look ahead: process current page + next page
    # For simplicity, let's process one page at a time for now as requested by the user,
    # and then discuss "look-ahead" as a refinement.
    # The current structure of the request implies a full chapter analysis is sent.
    # If "page-look ahead" means the frontend sends *only* current+next page,
    # then the frontend request structure would need to change.
    # For now, I'll process the full chapter, but group by page for output.

    temp_base_dir = None
    try:
        temp_base_dir = tempfile.mkdtemp()
        app.logger.info(f"Created base temporary directory: {temp_base_dir}")

        for page_num in sorted_page_numbers:
            page_paragraphs = paragraphs_by_page[page_num]
            
            segments_to_synthesize = process_paragraphs_for_synthesis(page_paragraphs)
            
            if not segments_to_synthesize:
                app.logger.warning(f"No valid text segments found for synthesis on page {page_num}.")
                page_audio_responses.append({
                    "pageNumber": page_num,
                    "audioContent": None,
                    "timestamps": [],
                    "error": "No text to synthesize for this page."
                })
                continue

            individual_audio_segments = []
            page_timestamps = []
            current_audio_duration_ms = 0

            # Create a temporary directory for this page's audio files
            page_temp_dir = os.path.join(temp_base_dir, f"page_{page_num}")
            os.makedirs(page_temp_dir, exist_ok=True)
            app.logger.info(f"Created temporary directory for page {page_num}: {page_temp_dir}")

            # 2) Perform speech synthesis for each segment and save
            for i, segment in enumerate(segments_to_synthesize):
                segment_text = segment['text']
                
                if not segment_text.strip():
                    app.logger.warning(f"Skipping synthesis for empty text segment {i} on page {page_num}.")
                    continue

                audio_base64, word_timings = _synthesize_speech_cached(segment_text, voice_name, language_code)
                audio_content = base64.b64decode(audio_base64)
                
                # Use pydub to load the audio from bytes
                audio_segment = AudioSegment.from_file(io.BytesIO(audio_content), format="mp3")
                individual_audio_segments.append(audio_segment)

                # Generate timestamps for original paragraphs within this segment
                # This requires careful mapping of word timings back to the original paragraphs
                # The `process_tts_response_for_timestamps` from previous suggestion would be needed here.
                # For now, a simplified timestamp based on segment duration:
                for original_p_info in segment["original_paragraphs"]:
                    page_timestamps.append({
                        "pageNumber": original_p_info["pageNumber"],
                        "paragraphIndexOnPage": original_p_info["paragraphIndexOnPage"],
                        "start_time_ms": current_audio_duration_ms,
                        "end_time_ms": current_audio_duration_ms + audio_segment.duration_seconds * 1000
                    })
                current_audio_duration_ms += audio_segment.duration_seconds * 1000

            if not individual_audio_segments:
                app.logger.warning(f"No audio segments generated for page {page_num}.")
                page_audio_responses.append({
                    "pageNumber": page_num,
                    "audioContent": None,
                    "timestamps": [],
                    "error": "No audio generated for this page."
                })
                continue

            # 3) Merge audio files using pydub
            merged_audio = AudioSegment.empty()
            for seg in individual_audio_segments:
                merged_audio += seg

            # Export the merged audio to a temporary file
            merged_audio_filename = f"merged_page_{page_num}.mp3"
            merged_audio_path = os.path.join(page_temp_dir, merged_audio_filename)
            merged_audio.export(merged_audio_path, format="mp3")
            app.logger.info(f"Merged audio for page {page_num} saved to: {merged_audio_path}")

            # Read the merged audio file and encode it to base64
            with open(merged_audio_path, 'rb') as f:
                merged_audio_content = f.read()
            merged_audio_base64 = base64.b64encode(merged_audio_content).decode('utf-8')

            page_audio_responses.append({
                "pageNumber": page_num,
                "audioContent": merged_audio_base64,
                "format": "audio/mpeg",
                "timestamps": page_timestamps # This will need refinement with word timings
            })

        return jsonify({
            "success": True,
            "pageAudioResponses": page_audio_responses,
            "message": "Chapter audio synthesized and merged per page."
        })

    except Exception as e:
        app.logger.error(f"An error occurred during chapter audio synthesis: {e}", exc_info=True)
        return jsonify({"error": f"An unexpected server error occurred: {str(e)}"}), 500
    finally:
        # Clean up the base temporary directory and its contents
        if temp_base_dir and os.path.exists(temp_base_dir):
            shutil.rmtree(temp_base_dir)
            app.logger.info(f"Cleaned up base temporary directory: {temp_base_dir}")

# --- Existing /synthesize-speech endpoint (can be kept or removed) ---
@app.route('/synthesize-speech', methods=['POST'])
def synthesize_speech_endpoint():
    # This endpoint can remain for simpler, unchunked synthesis requests if needed,
    # or you can refactor clients to use '/synthesize-chapter-audio' exclusively.
    
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    text_content = data.get('text')
    voice_name = data.get('voiceName')
    language_code = data.get('languageCode')

    if not all([text_content, voice_name, language_code]):
        return jsonify({"error": "Missing required parameters: text, voiceName, or languageCode"}), 400

    try:
        audio_base64, word_timings = _synthesize_speech_cached(text_content, voice_name, language_code)

        # Returning raw word timings here, as this endpoint doesn't have page/paragraph context
        return jsonify({
            "success": True,
            "audioContent": audio_base64,
            "format": "audio/mpeg",
            "wordTimings": [
                {"word": w.text_content, "start_time_ms": int((w.start_time.seconds + w.start_time.nanos * 1e-9) * 1000),
                 "end_time_ms": int((w.end_time.seconds + w.end_time.nanos * 1e-9) * 1000)}
                for w in word_timings
            ]
        })

    except Exception as e:
        app.logger.error(f"Error synthesizing speech: {e}", exc_info=True)
        if "credentials were not found" in str(e):
            return jsonify({"error": "Failed to synthesize speech: Google Cloud credentials error. See server logs for details."}), 500
        return jsonify({"error": f"Failed to synthesize speech: {str(e)}"}), 500

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
