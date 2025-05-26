import os
import json
from flask import Flask, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# --- Google Docs API Configuration ---
SCOPES = ['https://www.googleapis.com/auth/documents.readonly']

def get_docs_service():
    """Initializes and returns a Google Docs API service client."""
    try:
        creds_json = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON')
        if not creds_json:
            app.logger.error("GOOGLE_APPLICATION_CREDENTIALS_JSON environment variable not set.")
            raise ValueError("GOOGLE_APPLICATION_CREDENTIALS_JSON environment variable not set.")

        info = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        service = build('docs', 'v1', credentials=credentials)
        app.logger.info("Google Docs service initialized successfully.")
        return service
    except Exception as e:
        app.logger.error(f"Error initializing Google Docs service: {e}", exc_info=True)
        raise

# --- Helper function to extract text from Google Docs content ---
def extract_text_from_elements(elements):
    text_content = ""
    if not elements:
        return text_content
    for element in elements:
        if 'paragraph' in element:
            for text_run in element['paragraph']['elements']:
                if 'textRun' in text_run:
                    text_content += text_run['textRun']['content']
        elif 'table' in element:
            # Recursively extract content from table cells
            for row in element['table']['tableRows']:
                for cell in row['tableCells']:
                    text_content += extract_text_from_elements(cell['content']) + " | "
            text_content += "\n"
    return text_content


# --- API Endpoint to Fetch Document Content ---
@app.route('/get-doc-content', methods=['GET'])
def get_document_content():
    # --- AUTHENTICATION CHECK ---
    expected_api_key = os.environ.get('RAILWAY_APP_API_KEY')
    incoming_api_key = request.headers.get('X-API-Key') # Get key from X-API-Key header

    if not expected_api_key:
        app.logger.critical("RAILWAY_APP_API_KEY environment variable is not set in Railway!")
        return jsonify({"error": "Server configuration error: API key not set."}), 500

    if not incoming_api_key or incoming_api_key != expected_api_key:
        app.logger.warning(f"Unauthorized access attempt. Incoming key: '{incoming_api_key}'")
        return jsonify({"error": "Unauthorized access. Invalid API Key."}), 401
    # --- END AUTHENTICATION CHECK ---

    # *** DOCUMENT ID IS HARDCODED IN PYTHON API (CORRECTED ID) ***
    document_id = '1ubt637f0K87_Och3Pin9GbJM7w6wzf3M2RCmHbmHgYI' # Confirmed correct ID

    try:
        service = get_docs_service()
        app.logger.info(f"Fetching document with ID: {document_id}")
        # Make sure includeTabsContent=True is still there
        document = service.documents().get(documentId=document_id, includeTabsContent=True).execute()

        # --- DEBUGGING LOGS ---
        app.logger.info(f"Document fetched. Top-level keys: {list(document.keys())}")
        # Only log first 1000 characters to prevent overwhelming logs
        app.logger.info(f"Full document response (first 1000 chars): {json.dumps(document, indent=2)[:1000]}...")
        # --- END DEBUGGING LOGS ---

        parsed_data = {
            "title": document.get('title', 'Untitled Document'),
            "books": []
        }

        # --- MODIFIED LOGIC FOR HANDLING TABS ---
        if 'tabs' in document and document['tabs']:
            for i, tab_data in enumerate(document['tabs']):
                tab_properties = tab_data.get('tabProperties', {})
                document_tab = tab_data.get('documentTab', {})
                tab_body = document_tab.get('body', {})
                tab_content = tab_body.get('content', [])

                book_entry = {
                    "title": tab_properties.get('title', f"Tab {i+1}"),
                    "id": f"tab-{tab_properties.get('tabId', f'tab_{i+1}').replace('.', '_')}", # Use tabId or generate
                    "startIndex": tab_properties.get('range', {}).get('startIndex', 0),
                    "endIndex": tab_properties.get('range', {}).get('endIndex', 0),
                    "chapters": []
                }

                current_chapter = None
                chapter_counter = 0

                for element in tab_content: # Iterate through content of the current tab
                    start_index = element.get('startIndex', 0)
                    end_index = element.get('endIndex', 0)

                    if 'paragraph' in element:
                        paragraph = element['paragraph']
                        named_style_type = paragraph.get('paragraphStyle', {}).get('namedStyleType')
                        text_run_content = extract_text_from_elements([element])

                        if named_style_type == 'HEADING_1':
                            if current_chapter:
                                book_entry['chapters'].append(current_chapter)
                            chapter_counter += 1
                            current_chapter = {
                                "number": text_run_content.strip(),
                                "title": "",
                                "content": "",
                                "id": f"chapter-{book_entry['id']}-{chapter_counter}" # Unique ID per chapter within book
                            }
                        elif named_style_type == 'SUBTITLE':
                            if current_chapter and not current_chapter['title']:
                                current_chapter['title'] = text_run_content.strip()
                            else:
                                if current_chapter:
                                    current_chapter['content'] += text_run_content
                                else:
                                    # If subtitle without preceding H1, treat as part of an intro chapter
                                    if not book_entry['chapters'] and not current_chapter:
                                        chapter_counter += 1
                                        current_chapter = {
                                            "number": "0", "title": "Introduction", "content": "",
                                            "id": f"chapter-{book_entry['id']}-{chapter_counter}"
                                        }
                                        book_entry['chapters'].append(current_chapter)
                                    if current_chapter: # Ensure current_chapter is set
                                        current_chapter['content'] += text_run_content
                        else:
                            if current_chapter:
                                current_chapter['content'] += text_run_content
                            else:
                                # If general text without a heading, add to an 'Introduction' chapter if none exists
                                if not book_entry['chapters'] and not current_chapter:
                                    chapter_counter += 1
                                    current_chapter = {
                                        "number": "0", "title": "Introduction", "content": "",
                                        "id": f"chapter-{book_entry['id']}-{chapter_counter}"
                                    }
                                    book_entry['chapters'].append(current_chapter)
                                if current_chapter: # Ensure current_chapter is set
                                    current_chapter['content'] += text_run_content
                    else: # Handle non-paragraph elements like tables directly
                        element_text = extract_text_from_elements([element])
                        if current_chapter:
                            current_chapter['content'] += element_text
                        else:
                            # If no chapter, add to an 'Introduction' chapter
                            if not book_entry['chapters'] and not current_chapter:
                                continue
                            if current_chapter:
                                current_chapter['content'] += element_text

                if current_chapter:
                    book_entry['chapters'].append(current_chapter)

                parsed_data['books'].append(book_entry)
        else:
            # Fallback for documents without explicit 'tabs' (or if includeTabsContent is False)
            app.logger.warning("No 'tabs' found in document response. Assuming single main body.")
            main_body_content = document.get('body', {}).get('content', [])
            
            single_book_entry = {
                "title": document.get('title', 'Main Document'),
                "id": "tab-main",
                "startIndex": 0,
                "endIndex": len(json.dumps(document)), # Placeholder, actual end index of doc body
                "chapters": []
            }

            current_chapter = None
            chapter_counter = 0

            for element in main_body_content:
                # Reuse existing logic for main body content
                if 'paragraph' in element:
                    paragraph = element['paragraph']
                    named_style_type = paragraph.get('paragraphStyle', {}).get('namedStyleType')
                    text_run_content = extract_text_from_elements([element])

                    if named_style_type == 'HEADING_1':
                        if current_chapter:
                            single_book_entry['chapters'].append(current_chapter)
                        chapter_counter += 1
                        current_chapter = {
                            "number": text_run_content.strip(),
                            "title": "",
                            "content": "",
                            "id": f"chapter-main-{chapter_counter}"
                        }
                    elif named_style_type == 'SUBTITLE':
                        if current_chapter and not current_chapter['title']:
                            current_chapter['title'] = text_run_content.strip()
                        else:
                             if current_chapter:
                                current_chapter['content'] += text_run_content
                             else:
                                 if not single_book_entry['chapters'] and not current_chapter:
                                     chapter_counter += 1
                                     current_chapter = {
                                         "number": "0", "title": "Introduction", "content": "",
                                         "id": f"chapter-main-{chapter_counter}"
                                     }
                                     single_book_entry['chapters'].append(current_chapter)
                                 if current_chapter:
                                     current_chapter['content'] += text_run_content
                    else:
                        if current_chapter:
                            current_chapter['content'] += text_run_content
                        else:
                            if not single_book_entry['chapters'] and not current_chapter:
                                chapter_counter += 1
                                current_chapter = {
                                    "number": "0", "title": "Introduction", "content": "",
                                    "id": f"chapter-main-{chapter_counter}"
                                }
                                single_book_entry['chapters'].append(current_chapter)
                            if current_chapter:
                                current_chapter['content'] += text_run_content
                else:
                    element_text = extract_text_from_elements([element])
                    if current_chapter:
                        current_chapter['content'] += element_text
                    else:
                        if not single_book_entry['chapters'] and not current_chapter:
                            chapter_counter += 1
                            current_chapter = {
                                "number": "0", "title": "Introduction", "content": "",
                                "id": f"chapter-main-{chapter_counter}"
                            }
                            single_book_entry['chapters'].append(current_chapter)
                        if current_chapter:
                            current_chapter['content'] += element_text

            if current_chapter:
                single_book_entry['chapters'].append(current_chapter)

            parsed_data['books'].append(single_book_entry)
        # --- END MODIFIED LOGIC ---

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
