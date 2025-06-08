import os
import json
from flask import Flask, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from flask_cors import CORS
import re

# NEW IMPORTS FOR TEXT-TO-SPEECH
from google.cloud import texttospeech
import base64
from functools import lru_cache # Import lru_cache for caching

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

                    # --- CRITICAL FIX FOR SHIFT+ENTER ---
                    # Replace common non-standard line break characters with <br>
                    # U+000B (Line Tabulation) and U+0085 (Next Line)
                    # Also ensure standard newline \n is covered
                    processed_content = content.replace('\x0b', '<br>') \
                                     .replace('\x85', '<br>') \
                                     .replace('\n', '<br>') 

                    # Apply formatting based on textStyle properties
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
    # VERIFIED: This correctly loads the API key from the environment variable.
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
        
        # Keep includeTabsContent=True as it's essential for your book/chapter structure
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
# It's important that `_synthesize_speech_cached` is outside the Flask route function
# because lru_cache doesn't work directly on methods decorated with @app.route.
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
        audio_encoding=texttospeech.AudioEncoding.MP3
    )

    response = client.synthesize_speech(
        input=synthesis_input, voice=voice_params, audio_config=audio_config
    )

    audio_base64 = base64.b64encode(response.audio_content).decode('utf-8')
    return audio_base64

# --- NEW: API Endpoint to Synthesize Speech ---
@app.route('/synthesize-speech', methods=['POST'])
def synthesize_speech_endpoint():
    """
    API endpoint to synthesize speech using Google Cloud Text-to-Speech.
    Expects JSON payload with 'text', 'voiceName', 'languageCode'.
    Returns base64 encoded audio content.
    Includes caching to prevent duplicate TTS calls.
    """
    # Basic request validation
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    text_content = data.get('text')
    voice_name = data.get('voiceName')
    language_code = data.get('languageCode')

    if not all([text_content, voice_name, language_code]):
        return jsonify({"error": "Missing required parameters: text, voiceName, or languageCode"}), 400

    try:
        # Call the cached synthesis function
        audio_base64 = _synthesize_speech_cached(text_content, voice_name, language_code)

        return jsonify({
            "success": True,
            "audioContent": audio_base64,
            "format": "audio/mpeg"
        })

    except Exception as e:
        app.logger.error(f"Error synthesizing speech: {e}", exc_info=True)
        if "credentials were not found" in str(e):
             return jsonify({"error": "Failed to synthesize speech: Google Cloud credentials error. See server logs for details."}), 500
        return jsonify({"error": f"Failed to synthesize speech: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
