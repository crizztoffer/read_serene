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
import io
import tempfile
import shutil
import math

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
        return jsonify({"error": f"An unexpected server error occurred: {str(e)}"}), 500


# Use lru_cache to cache the synthesis results. Max size can be adjusted.
@lru_cache(maxsize=128)
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
    )

    response = client.synthesize_speech(
        input=synthesis_input, voice=voice_params, audio_config=audio_config
    )

    return base64.b64encode(response.audio_content).decode('utf-8'), []

# --- NEW LOGIC FOR SPEECH SYNTHESIS INTEGRATION ---

MAX_CHAR_COUNT_FOR_NARRATION = 768

def process_paragraphs_for_synthesis(paragraphs_data):
    """
    Processes the incoming paragraphs (from frontend JSON) to create a new list of segments
    optimized for speech synthesis, applying concatenation rules based on paragraph type.
    Each segment will also include the original paragraph indices it covers.
    """
    synthesis_segments = []
    current_narration_buffer = []
    current_narration_char_count = 0
    current_narration_original_indices = []

    for paragraph in paragraphs_data:
        text = paragraph.get('text', '').strip()
        paragraph_type = paragraph.get('paragraphType', 'narration')
        original_page_number = paragraph.get('pageNumber')
        original_paragraph_index_on_page = paragraph.get('paragraphIndexOnPage')

        if not text and paragraph_type != 'horizontal_rule': # Don't skip horizontal_rule even if text is empty
            continue

        original_paragraph_meta = {
            "pageNumber": original_page_number,
            "paragraphIndexOnPage": original_paragraph_index_on_page,
            "text": text,
            "paragraphType": paragraph_type # Include paragraphType in meta
        }

        if paragraph_type == 'horizontal_rule':
            # If there's an active narration buffer, finalize it before adding horizontal_rule
            if current_narration_buffer:
                synthesis_segments.append({
                    "text": " ".join(current_narration_buffer),
                    "type": "narration",
                    "original_paragraphs_meta": current_narration_original_indices
                })
                current_narration_buffer = []
                current_narration_char_count = 0
                current_narration_original_indices = []
            
            # Add horizontal_rule as its own segment
            synthesis_segments.append({
                "text": "", # No text to synthesize for horizontal rule
                "type": "horizontal_rule",
                "original_paragraphs_meta": [original_paragraph_meta]
            })
        elif paragraph_type == 'narration':
            potential_new_char_count = current_narration_char_count + len(text) + (1 if current_narration_buffer else 0)
            
            if current_narration_buffer and potential_new_char_count > MAX_CHAR_COUNT_FOR_NARRATION:
                synthesis_segments.append({
                    "text": " ".join(current_narration_buffer),
                    "type": "narration",
                    "original_paragraphs_meta": current_narration_original_indices
                })
                current_narration_buffer = [text]
                current_narration_char_count = len(text)
                current_narration_original_indices = [original_paragraph_meta]
            else:
                current_narration_buffer.append(text)
                current_narration_char_count = potential_new_char_count
                current_narration_original_indices.append(original_paragraph_meta)

        else: # Dialogue or Italicized type
            if current_narration_buffer:
                synthesis_segments.append({
                    "text": " ".join(current_narration_buffer),
                    "type": "narration",
                    "original_paragraphs_meta": current_narration_original_indices
                })
                current_narration_buffer = []
                current_narration_char_count = 0
                current_narration_original_indices = []
            
            synthesis_segments.append({
                "text": text,
                "type": paragraph_type,
                "original_paragraphs_meta": [original_paragraph_meta]
            })

    if current_narration_buffer:
        synthesis_segments.append({
            "text": " ".join(current_narration_buffer),
            "type": "narration",
            "original_paragraphs_meta": current_narration_original_indices
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
    page_paragraphs_from_frontend = data.get('chapterParagraphs')
    voice_name = data.get('voiceName')
    language_code = data.get('languageCode')

    if not page_paragraphs_from_frontend or not isinstance(page_paragraphs_from_frontend, list):
        return jsonify({"error": "Invalid or empty 'chapterParagraphs' received."}), 400
    if not all([voice_name, language_code]):
        return jsonify({"error": "Missing required parameters: 'voiceName' or 'languageCode'"}), 400

    page_num = page_paragraphs_from_frontend[0].get('pageNumber') if page_paragraphs_from_frontend else None

    app.logger.info(f"Received {len(page_paragraphs_from_frontend)} paragraphs for single page synthesis (Page: {page_num}).")
    app.logger.info(f"Requested voice: {voice_name}, language: {language_code}")

    temp_base_dir = None
    try:
        temp_base_dir = tempfile.mkdtemp()
        app.logger.info(f"Created base temporary directory: {temp_base_dir}")

        segments_to_synthesize = process_paragraphs_for_synthesis(page_paragraphs_from_frontend)
        
        if not segments_to_synthesize:
            app.logger.warning(f"No valid text segments found for synthesis on page {page_num}.")
            return jsonify({
                "pageNumber": page_num,
                "audioContent": None,
                "timestamps": [],
                "error": "No text to synthesize for this page."
            }), 200

        individual_audio_segments_pydub = []
        cumulative_segment_timestamps = []

        page_temp_dir = os.path.join(temp_base_dir, f"page_{page_num}")
        os.makedirs(page_temp_dir, exist_ok=True)
        app.logger.info(f"Created temporary directory for page {page_num}: {page_temp_dir}")

        current_page_audio_offset_ms = 0
        for i, segment in enumerate(segments_to_synthesize):
            segment_text = segment['text']
            segment_type = segment['type']
            
            audio_segment_pydub = None
            segment_duration_ms = 0

            if segment_type == 'horizontal_rule':
                silence_duration_ms = 800  # 0.8 seconds
                audio_segment_pydub = AudioSegment.silent(duration=silence_duration_ms)
                segment_duration_ms = silence_duration_ms
                app.logger.info(f"Added {silence_duration_ms}ms silence for horizontal_rule at segment {i} on page {page_num}.")
            elif not segment_text.strip():
                app.logger.warning(f"Skipping synthesis for empty text segment {i} on page {page_num}.")
                continue
            else:
                audio_base64, _ = _synthesize_speech_cached(segment_text, voice_name, language_code) 
                audio_content_bytes = base64.b64decode(audio_base64)
                
                audio_segment_pydub = AudioSegment.from_file(io.BytesIO(audio_content_bytes), format="mp3")
                segment_duration_ms = audio_segment_pydub.duration_seconds * 1000

            individual_audio_segments_pydub.append(audio_segment_pydub)

            # Generate timestamps for the original paragraphs within this *segment*
            total_chars_in_segment = sum(len(p['text']) for p in segment["original_paragraphs_meta"])
            
            cumulative_char_in_segment = 0
            for p_meta in segment["original_paragraphs_meta"]:
                paragraph_char_count = len(p_meta['text'])
                
                # If it's a horizontal rule, it contributes fixed silent duration
                if p_meta['paragraphType'] == 'horizontal_rule':
                     # The entire 0.8s silence is for this single horizontal rule
                    start_time_relative_to_segment = 0 
                    end_time_relative_to_segment = 800 
                else:
                    start_time_relative_to_segment = (cumulative_char_in_segment / total_chars_in_segment) * segment_duration_ms if total_chars_in_segment > 0 else 0
                    cumulative_char_in_segment += paragraph_char_count
                    if segment['type'] == 'narration' and p_meta != segment["original_paragraphs_meta"][-1]:
                           cumulative_char_in_segment += 1 # Account for space
                    
                    end_time_relative_to_segment = (cumulative_char_in_segment / total_chars_in_segment) * segment_duration_ms if total_chars_in_segment > 0 else 0


                cumulative_segment_timestamps.append({
                    "pageNumber": p_meta['pageNumber'],
                    "paragraphIndexOnPage": p_meta['paragraphIndexOnPage'],
                    "start_time_ms": int(current_page_audio_offset_ms + start_time_relative_to_segment),
                    "end_time_ms": int(current_page_audio_offset_ms + end_time_relative_to_segment)
                })
            
            current_page_audio_offset_ms += segment_duration_ms

            # Add 0.5 seconds of silence *after* each segment, unless it's the very last one
            if i < len(segments_to_synthesize) - 1:
                silence = AudioSegment.silent(duration=500) # 0.5 seconds of silence
                individual_audio_segments_pydub.append(silence)
                current_page_audio_offset_ms += 500 # Account for silence in cumulative offset


        if not individual_audio_segments_pydub:
            app.logger.warning(f"No audio segments generated for page {page_num}.")
            return jsonify({
                "pageNumber": page_num,
                "audioContent": None,
                "timestamps": [],
                "error": "No audio generated for this page."
            }), 200

        merged_audio = AudioSegment.empty()
        for seg in individual_audio_segments_pydub:
            merged_audio += seg

        merged_audio_filename = f"merged_page_{page_num}.mp3"
        merged_audio_path = os.path.join(page_temp_dir, merged_audio_filename)
        merged_audio.export(merged_audio_path, format="mp3")
        app.logger.info(f"Merged audio for page {page_num} saved to: {merged_audio_path}")

        with open(merged_audio_path, 'rb') as f:
            merged_audio_content = f.read()
        
        merged_audio_base64 = base64.b64encode(merged_audio_content).decode('utf-8')

        return jsonify({
            "success": True,
            "pageNumber": page_num,
            "audioContent": merged_audio_base64,
            "format": "audio/mpeg",
            "timestamps": cumulative_segment_timestamps,
            "message": f"Audio synthesized and merged for page {page_num}."
        })

    except Exception as e:
        app.logger.error(f"An error occurred during single page audio synthesis: {e}", exc_info=True)
        return jsonify({"error": f"An unexpected server error occurred: {str(e)}"}), 500
    finally:
        if temp_base_dir and os.path.exists(temp_base_dir):
            shutil.rmtree(temp_base_dir)
            app.logger.info(f"Cleaned up base temporary directory: {temp_base_dir}")

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
