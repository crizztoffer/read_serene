import os
import json
import base64
import re  # Regular expressions

from flask import Flask, request, jsonify
from flask_cors import CORS

# Google Cloud & Docs API
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Google Cloud Text-to-Speech
from google.cloud import texttospeech

# --- Flask App Setup ---
app = Flask(__name__)
CORS(app)

# --- Constants ---
SCOPES = ['https://www.googleapis.com/auth/documents.readonly']

# --- Helper: Load Google Cloud Credentials ---
def get_google_cloud_credentials():
    try:
        creds_json = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON')
        if not creds_json:
            raise ValueError("GOOGLE_APPLICATION_CREDENTIALS_JSON environment variable not set.")

        info = json.loads(creds_json)
        return service_account.Credentials.from_service_account_info(info)
    except Exception as e:
        app.logger.error(f"Error loading credentials: {e}", exc_info=True)
        raise

# --- Helper: Build Google Docs API Client ---
def get_docs_service():
    try:
        credentials = get_google_cloud_credentials()
        return build('docs', 'v1', credentials=credentials)
    except Exception as e:
        app.logger.error(f"Error initializing Docs service: {e}", exc_info=True)
        raise

# --- Helper: Extract Formatted HTML from Document Elements ---
def extract_formatted_html_from_elements(elements):
    html_content = ""

    for element in elements:
        if 'paragraph' in element:
            paragraph_html_parts = []

            for text_run in element['paragraph']['elements']:
                if 'textRun' in text_run:
                    content = text_run['textRun']['content'].replace('\n', '<br>')
                    text_style = text_run['textRun'].get('textStyle', {})

                    if text_style.get('bold'):
                        content = f"<strong>{content}</strong>"
                    if text_style.get('italic'):
                        content = f"<em>{content}</em>"
                    if text_style.get('underline'):
                        content = f"<u>{content}</u>"

                    paragraph_html_parts.append(content)

                elif 'horizontalRule' in text_run:
                    paragraph_html_parts.append("<hr>")

            full_paragraph_content = "".join(paragraph_html_parts)
            stripped_text = re.sub(r'<[^>]*>', '', full_paragraph_content).strip()

            if stripped_text == "":
                if '<br>' in full_paragraph_content or '<hr>' in full_paragraph_content:
                    html_content += f"<p>{full_paragraph_content}</p>"
                else:
                    html_content += "<p></p>"
            else:
                if full_paragraph_content.endswith('<br>') and (len(stripped_text) > 0 or full_paragraph_content.count('<br>') > 1):
                    html_content += f"<p>{full_paragraph_content.rstrip('<br>').strip()}</p>"
                else:
                    html_content += f"<p>{full_paragraph_content.strip()}</p>"

        elif 'table' in element:
            table_html = "<table>"
            for row in element['table']['tableRows']:
                table_html += "<tr>"
                for cell in row['tableCells']:
                    table_html += f"<td>{extract_formatted_html_from_elements(cell['content'])}</td>"
                table_html += "</tr>"
            table_html += "</table>\n"
            html_content += table_html

    return html_content

# --- API: Fetch Google Doc Content ---
@app.route('/get-doc-content', methods=['GET'])
def get_document_content():
    expected_api_key = os.environ.get('RAILWAY_APP_API_KEY')
    incoming_api_key = request.headers.get('X-API-Key')

    if not expected_api_key:
        return jsonify({"error": "Server configuration error: API key not set."}), 500
    if not incoming_api_key or incoming_api_key != expected_api_key:
        return jsonify({"error": "Unauthorized access. Invalid API Key."}), 401

    document_id = '1ubt637f0K87_Och3Pin9GbJM7w6wzf3M2RCmHbmHgYI'

    try:
        service = get_docs_service()
        document = service.documents().get(documentId=document_id, includeTabsContent=True).execute()

        parsed_data = {
            "title": document.get('title', 'Untitled Document'),
            "document_id": document_id,
            "books": []
        }

        if 'tabs' in document and document['tabs']:
            for i, tab_data in enumerate(document['tabs']):
                tab_props = tab_data.get('tabProperties', {})
                tab_body = tab_data.get('documentTab', {}).get('body', {})
                content = tab_body.get('content', [])

                book_entry = {
                    "title": tab_props.get('title', f"Tab {i+1}"),
                    "id": f"tab-{tab_props.get('tabId', f'tab_{i+1}').replace('.', '_')}",
                    "chapters": []
                }

                current_chapter = None
                chapter_counter = 0

                for element in content:
                    named_style = element.get('paragraph', {}).get('paragraphStyle', {}).get('namedStyleType')
                    html = extract_formatted_html_from_elements([element])

                    if named_style == 'HEADING_1':
                        if current_chapter:
                            book_entry['chapters'].append(current_chapter)
                        chapter_counter += 1
                        number = re.sub(r'<[^>]*>', '', html).strip()
                        current_chapter = {
                            "number": number,
                            "title": "",
                            "content": "",
                            "id": f"chapter-{book_entry['id']}-{chapter_counter}"
                        }
                    elif named_style == 'SUBTITLE':
                        subtitle = re.sub(r'<[^>]*>', '', html).strip()
                        if current_chapter and not current_chapter['title']:
                            current_chapter['title'] = subtitle
                        elif current_chapter:
                            current_chapter['content'] += html
                        else:
                            chapter_counter += 1
                            current_chapter = {
                                "number": "0", "title": "Introduction", "content": html,
                                "id": f"chapter-{book_entry['id']}-{chapter_counter}"
                            }
                    else:
                        if not current_chapter:
                            chapter_counter += 1
                            current_chapter = {
                                "number": "0", "title": "Introduction", "content": html,
                                "id": f"chapter-{book_entry['id']}-{chapter_counter}"
                            }
                        else:
                            current_chapter['content'] += html

                if current_chapter:
                    book_entry['chapters'].append(current_chapter)

                parsed_data['books'].append(book_entry)

        else:
            # No tabs, fallback
            content = document.get('body', {}).get('content', [])
            single_book = {
                "title": document.get('title', 'Main Document'),
                "id": "book-main",
                "chapters": []
            }

            current_chapter = None
            chapter_counter = 0

            for element in content:
                named_style = element.get('paragraph', {}).get('paragraphStyle', {}).get('namedStyleType')
                html = extract_formatted_html_from_elements([element])

                if named_style == 'HEADING_1':
                    if current_chapter:
                        single_book['chapters'].append(current_chapter)
                    chapter_counter += 1
                    number = re.sub(r'<[^>]*>', '', html).strip()
                    current_chapter = {
                        "number": number,
                        "title": "",
                        "content": "",
                        "id": f"chapter-main-{chapter_counter}"
                    }
                elif named_style == 'SUBTITLE':
                    subtitle = re.sub(r'<[^>]*>', '', html).strip()
                    if current_chapter and not current_chapter['title']:
                        current_chapter['title'] = subtitle
                    elif current_chapter:
                        current_chapter['content'] += html
                    else:
                        chapter_counter += 1
                        current_chapter = {
                            "number": "0", "title": "Introduction", "content": html,
                            "id": f"chapter-main-{chapter_counter}"
                        }
                else:
                    if not current_chapter:
                        chapter_counter += 1
                        current_chapter = {
                            "number": "0", "title": "Introduction", "content": html,
                            "id": f"chapter-main-{chapter_counter}"
                        }
                    else:
                        current_chapter['content'] += html

            if current_chapter:
                single_book['chapters'].append(current_chapter)

            parsed_data['books'].append(single_book)

        parsed_data['books'] = [book for book in parsed_data['books'] if book['chapters']]
        return jsonify(parsed_data)

    except HttpError as e:
        return jsonify({"error": f"Google API Error: {e.reason}", "code": e.status_code}), e.status_code
    except ValueError as e:
        return jsonify({"error": str(e)}), 500
    except KeyError as e:
        return jsonify({"error": f"Missing key {e}. Possibly bad permissions or document structure."}), 500
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500

# --- API: Text-to-Speech ---
@app.route('/synthesize-speech', methods=['POST'])
def synthesize_speech_endpoint():
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    text_content = data.get('text')
    voice_name = data.get('voiceName')
    language_code = data.get('languageCode')

    if not all([text_content, voice_name, language_code]):
        return jsonify({"error": "Missing required parameters: text, voiceName, languageCode"}), 400

    try:
        credentials = get_google_cloud_credentials()
        client = texttospeech.TextToSpeechClient(credentials=credentials)

        synthesis_input = texttospeech.SynthesisInput(text=text_content)
        voice = texttospeech.VoiceSelectionParams(language_code=language_code, name=voice_name)
        audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)

        response = client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)
        audio_base64 = base64.b64encode(response.audio_content).decode('utf-8')

        return jsonify({
            "success": True,
            "audioContent": audio_base64,
            "format": "audio/mpeg"
        })

    except Exception as e:
        return jsonify({"error": f"Failed to synthesize speech: {str(e)}"}), 500

# --- Run the Flask App ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
