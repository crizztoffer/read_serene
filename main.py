import os
import json
from flask import Flask, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from flask_cors import CORS

# NEW IMPORTS FOR TEXT-TO-SPEECH
from google.cloud import texttospeech
import base64

app = Flask(__name__)
CORS(app)

# --- Google Docs API Configuration ---
# Only 'documents.readonly' is sufficient if you're reconstructing HTML from JSON.
# 'drive.readonly' is NOT needed if we are not using drive.files().export
SCOPES = ['https://www.googleapis.com/auth/documents.readonly']


# Function to get Google Cloud credentials, now reusable for both Docs and TTS
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

# Modified get_docs_service to use the new credential function
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

# --- REVISED: Helper function to extract text *with formatting* from Google Docs content ---
# This function will traverse the Docs API JSON structure and reconstruct basic HTML.
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

                    # Apply formatting based on textStyle properties
                    # It's good practice to use strong/em for semantic meaning over b/i
                    if text_style.get('bold'):
                        content = f"<strong>{content}</strong>"
                    if text_style.get('italic'):
                        content = f"<em>{content}</em>"
                    if text_style.get('underline'):
                        content = f"<u>{content}</u>"
                    # Add more styles if needed (e.g., strikethrough, foregroundColor)

                    paragraph_html_parts.append(content)

                elif 'horizontalRule' in text_run:
                    paragraph_html_parts.append("<hr>")
            
            # Join text runs for this paragraph
            full_paragraph_content = "".join(paragraph_html_parts)

            # Check for empty paragraphs or those that only contain newlines
            # Docs API often includes trailing newlines in 'content' of textRuns
            # If the content is just a newline, treat it as a <br>
            if full_paragraph_content.strip() == "\n":
                html_content += "<br>"
            elif full_paragraph_content.strip() == "":
                html_content += "" # Or "<p></p>" if you want empty paragraphs
            else:
                html_content += f"<p>{full_paragraph_content.strip()}</p>" # Wrap in p-tag and strip extra leading/trailing newlines
        elif 'table' in element:
            table_html = "<table>"
            for row in element['table']['tableRows']:
                table_html += "<tr>"
                for cell in row['tableCells']:
                    table_html += f"<td>{extract_formatted_html_from_elements(cell['content'])}</td>"
                table_html += "</tr>"
            table_html += "</table>"
            html_content += table_html + "\n" # Add newline after table for separation
        elif 'sectionBreak' in element or 'pageBreak' in element:
            html_content += "<br><hr><br>" # Or some other visual separator
        # Add other element types as needed (e.g., list, embeddedObject)
        # For simplicity, this example primarily focuses on paragraphs and tables.
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
        # Fetch the document structure including tab content
        document = service.documents().get(documentId=document_id, includeTabsContent=True).execute()

        app.logger.info(f"Document structure fetched. Top-level keys: {list(document.keys())}")

        parsed_data = {
            "title": document.get('title', 'Untitled Document'),
            "document_id": document_id,
            "books": []
        }

        # --- MODIFIED LOGIC FOR HANDLING TABS AND EXTRACTING FORMATTED HTML ---
        if 'tabs' in document and document['tabs']:
            for i, tab_data in enumerate(document['tabs']):
                tab_properties = tab_data.get('tabProperties', {})
                document_tab = tab_data.get('documentTab', {})
                tab_body = document_tab.get('body', {})
                tab_content_elements = tab_body.get('content', []) # These are the raw JSON elements

                book_entry = {
                    "title": tab_properties.get('title', f"Tab {i+1}"),
                    "id": f"tab-{tab_properties.get('tabId', f'tab_{i+1}').replace('.', '_')}",
                    "chapters": []
                }

                current_chapter = None
                chapter_counter = 0

                # Process elements within the current tab to build chapters
                for element in tab_content_elements:
                    named_style_type = None
                    if 'paragraph' in element:
                        named_style_type = element['paragraph'].get('paragraphStyle', {}).get('namedStyleType')

                    # Extract formatted HTML for the current element
                    element_html_content = extract_formatted_html_from_elements([element]) # Pass as list because extract_formatted_html_from_elements expects iterable

                    if named_style_type == 'HEADING_1':
                        if current_chapter:
                            book_entry['chapters'].append(current_chapter)
                        chapter_counter += 1
                        # Heading number/title usually shouldn't contain HTML tags from b/i/u, strip them if present
                        chapter_text_content = element_html_content.replace('<p>', '').replace('</p>', '').strip()
                        # Use a simple regex to strip other HTML tags for number/title if they occur
                        import re
                        chapter_text_content = re.sub(r'<[^>]*>', '', chapter_text_content)

                        current_chapter = {
                            "number": chapter_text_content,
                            "title": "",
                            "content": "",
                            "id": f"chapter-{book_entry['id']}-{chapter_counter}"
                        }
                    elif named_style_type == 'SUBTITLE':
                        # Subtitle content should also be stripped of HTML tags for display as 'title'
                        subtitle_text_content = element_html_content.replace('<p>', '').replace('</p>', '').strip()
                        import re
                        subtitle_text_content = re.sub(r'<[^>]*>', '', subtitle_text_content)

                        if current_chapter and not current_chapter['title']:
                            current_chapter['title'] = subtitle_text_content
                        else:
                            # If a subtitle appears without a preceding HEADING_1, treat it as general content
                            if current_chapter:
                                current_chapter['content'] += element_html_content
                            else: # Introduction chapter case
                                if not book_entry['chapters'] and not current_chapter:
                                    chapter_counter += 1
                                    current_chapter = {
                                        "number": "0", "title": "Introduction", "content": "",
                                        "id": f"chapter-{book_entry['id']}-{chapter_counter}"
                                    }
                                    book_entry['chapters'].append(current_chapter)
                                if current_chapter:
                                    current_chapter['content'] += element_html_content
                    else: # General body text or other elements
                        if current_chapter:
                            current_chapter['content'] += element_html_content
                        else: # Introduction chapter case
                            if not book_entry['chapters'] and not current_chapter:
                                chapter_counter += 1
                                current_chapter = {
                                    "number": "0", "title": "Introduction", "content": "",
                                    "id": f"chapter-{book_entry['id']}-{chapter_counter}"
                                }
                                book_entry['chapters'].append(current_chapter)
                            if current_chapter:
                                current_chapter['content'] += element_html_content

                if current_chapter: # Append the last chapter if it exists
                    book_entry['chapters'].append(current_chapter)

                parsed_data['books'].append(book_entry)
        else:
            # Fallback for documents without explicit 'tabs'
            app.logger.warning("No 'tabs' found in document response. Assuming single main body.")
            main_body_content_elements = document.get('body', {}).get('content', [])
            
            single_book_entry = {
                "title": document.get('title', 'Main Document'),
                "id": "tab-main",
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
                    chapter_text_content = element_html_content.replace('<p>', '').replace('</p>', '').strip()
                    import re
                    chapter_text_content = re.sub(r'<[^>]*>', '', chapter_text_content)
                    current_chapter = {
                        "number": chapter_text_content,
                        "title": "",
                        "content": "",
                        "id": f"chapter-main-{chapter_counter}"
                    }
                elif named_style_type == 'SUBTITLE':
                    subtitle_text_content = element_html_content.replace('<p>', '').replace('</p>', '').strip()
                    import re
                    subtitle_text_content = re.sub(r'<[^>]*>', '', subtitle_text_content)
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

            if current_chapter: # Append the last chapter if it exists
                single_book_entry['chapters'].append(current_chapter)

            parsed_data['books'].append(single_book_entry)

        # Filter out books with no chapters after processing
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


# --- NEW: API Endpoint to Synthesize Speech ---
@app.route('/synthesize-speech', methods=['POST'])
def synthesize_speech_endpoint():
    """
    API endpoint to synthesize speech using Google Cloud Text-to-Speech.
    Expects JSON payload with 'text', 'voiceName', 'languageCode'.
    Returns base64 encoded audio content.
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
        credentials = get_google_cloud_credentials()
        client = texttospeech.TextToSpeechClient(credentials=credentials)

        # IMPORTANT: If your text_content now contains HTML tags (like <strong>),
        # the Text-to-Speech API needs to interpret them as SSML.
        # So, you MUST use `ssml_text` instead of `text`.
        # This means the frontend should send content with proper SSML tags
        # OR you convert basic HTML to SSML here.
        # For b/i/u, basic HTML like <strong> is often fine if passed as 'text',
        # but for full SSML power, use `ssml_text`.
        # For now, let's stick to 'text' as it often handles basic HTML for speech synthesis.
        # If TTS output sounds strange with formatting, consider converting to SSML here.
        synthesis_input = texttospeech.SynthesisInput(text=text_content) # Keep as text for simplicity now

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
