import os
import json
from flask import Flask, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from flask_cors import CORS
import re # Import for regular expressions

# NEW IMPORTS FOR TEXT-TO-SPEECH
from google.cloud import texttospeech
import base64

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

# --- REVISED: Helper function to extract text *with formatting* from Google Docs content ---
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

                    # 1. Handle Shift+Enter (soft line breaks) by replacing \n with <br>
                    # Ensure it only replaces actual newlines, not those that imply paragraph end
                    # The Google Docs API usually gives a trailing \n for a paragraph textRun.
                    # We want to convert \n *within* the text.
                    # The .strip() at the end when creating the <p> tag will handle trailing \n.
                    processed_content = content.replace('\n', '<br>')
                    
                    # 2. Apply formatting based on textStyle properties
                    if text_style.get('bold'):
                        processed_content = f"<strong>{processed_content}</strong>"
                    if text_style.get('italic'):
                        processed_content = f"<em>{processed_content}</em>"
                    if text_style.get('underline'):
                        processed_content = f"<u>{processed_content}</u>"
                    
                    paragraph_html_parts.append(processed_content)
                
                # 3. Handle Horizontal Rules (explicit check for horizontalRule element)
                elif 'horizontalRule' in text_run:
                    paragraph_html_parts.append("<hr>")

            full_paragraph_content = "".join(paragraph_html_parts)

            # Post-process for paragraph wrapping and excess <br> tags.
            # If a paragraph was just a series of soft breaks, `paragraph_html_parts` could be `['<br><br>']`
            # If Google Docs includes a trailing newline in textRun.content for paragraph breaks,
            # this might result in an extra <br> at the end of `full_paragraph_content`.
            # We want to remove that if the paragraph contains actual text AND it ends with <br>.
            
            # Simple check for genuinely empty paragraphs (after all processing)
            temp_stripped_content = re.sub(r'<[^>]*>', '', full_paragraph_content).strip() # strip all HTML tags and whitespace

            if temp_stripped_content == "":
                # If the paragraph is truly empty of meaningful content (only spaces, newlines, or HRs)
                # and it results in no text after stripping HTML.
                # If it was an actual user-inserted empty line or sequence of soft returns,
                # let's just make it a <p><br></p> to preserve some vertical spacing if needed.
                if '<br>' in full_paragraph_content or '<hr>' in full_paragraph_content:
                     html_content += f"<p>{full_paragraph_content}</p>"
                else:
                     html_content += "<p></p>" # Truly empty paragraph
            else:
                # If there's actual content, wrap in <p> and ensure no redundant trailing <br>
                # Remove a trailing <br> if it exists, as the <p> naturally provides a block break.
                if full_paragraph_content.endswith('<br>'):
                    # Remove the last <br> only if it's not the only content
                    if full_paragraph_content.count('<br>') == (len(full_paragraph_content.replace('<br>', '')) == 0): # Check if only <br>s
                        html_content += f"<p>{full_paragraph_content}</p>" # Preserve if it's just <br>s
                    else:
                        html_content += f"<p>{full_paragraph_content[:-4].strip()}</p>" # Remove last <br> for regular content
                else:
                    html_content += f"<p>{full_paragraph_content.strip()}</p>"
        
        # Existing table handling remains the same
        elif 'table' in element:
            table_html = "<table>"
            for row in element['table']['tableRows']:
                table_html += "<tr>"
                for cell in row['tableCells']:
                    table_html += f"<td>{extract_formatted_html_from_elements(cell['content'])}</td>"
                table_html += "</tr>"
            table_html += "</table>"
            html_content += table_html + "\n"
        
        # If you still want to represent section breaks visually, uncomment and adjust:
        # elif 'sectionBreak' in element or 'pageBreak' in element:
        #     html_content += "<div class='section-break-indicator'></div>" # Or <hr> if it makes sense contextually

    return html_content

# --- API Endpoint to Fetch Document Content (remains largely same, uses updated helper) ---
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
        # Note: 'includeTabsContent' might not be standard Docs API param. 
        # If it causes an error, remove it. Docs API typically structures content in 'body'.
        # If "tabs" are a custom interpretation by another service, that service's API would define it.
        # Assuming your previous usage of 'tabs' key was working with some custom API or recent undocumented Docs API feature.
        document = service.documents().get(documentId=document_id).execute() # Removed includeTabsContent for standard API

        app.logger.info(f"Document structure fetched. Top-level keys: {list(document.keys())}")

        parsed_data = {
            "title": document.get('title', 'Untitled Document'),
            "document_id": document_id,
            "books": []
        }

        # --- MODIFIED LOGIC FOR HANDLING TABS AND EXTRACTING FORMATTED HTML ---
        # Reverting to typical Docs API structure; 'tabs' is not a standard top-level key.
        # Assuming chapters are determined by HEADING_1 styles within the main body.
        
        main_body_content_elements = document.get('body', {}).get('content', [])
            
        book_entry = {
            "title": document.get('title', 'Main Document'),
            "id": "book-main", # Changed from tab-main for clarity
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
                    book_entry['chapters'].append(current_chapter)
                chapter_counter += 1
                chapter_text_content = re.sub(r'<[^>]*>', '', element_html_content).strip()
                current_chapter = {
                    "number": chapter_text_content, # Number is the text of the H1
                    "title": "", # Title will be filled by SUBTITLE if present
                    "content": "",
                    "id": f"chapter-{book_entry['id']}-{chapter_counter}"
                }
            elif named_style_type == 'SUBTITLE':
                subtitle_text_content = re.sub(r'<[^>]*>', '', element_html_content).strip()
                if current_chapter and not current_chapter['title']: # If current chapter has no title yet
                    current_chapter['title'] = subtitle_text_content
                else: # If subtitle appears without a preceding HEADING_1, or after one with a title, treat as content
                    if current_chapter:
                        current_chapter['content'] += element_html_content
                    else: # Case for beginning of document, before any H1, treat as 'Introduction'
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
                else: # Case for beginning of document, before any H1 or Subtitle
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

        # It's generally safe to pass basic HTML tags (like <strong>, <em>, <u>, <br>)
        # directly to Text-to-Speech's 'text' input. It will often interpret them correctly
        # for pauses or emphasis. If you need more nuanced control, you would convert to SSML.
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
