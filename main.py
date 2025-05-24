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
            for row in element['table']['tableRows']:
                for cell in row['tableCells']:
                    text_content += extract_text_from_elements(cell['content']) + " | "
            text_content += "\n"
    return text_content

# --- API Endpoint to Fetch Document Content ---
@app.route('/get-doc-content', methods=['GET'])
def get_document_content():
    # *** DOCUMENT ID IS NOW DEFINED HERE DIRECTLY IN PYTHON ***
    # IMPORTANT: Replace '1ubt637f0K87_Och3Pin9GbJM7w6wzf3M2RCHbmHgYI' with YOUR ACTUAL Google Doc ID
    document_id = '1ubt637f0K87_Och3Pin9GbJM7w6wzf3M2RCHbmHgYI'

    # The check for 'document_id' missing from query parameters is no longer needed
    # because it's now hardcoded here.

    try:
        service = get_docs_service()
        app.logger.info(f"Fetching document with ID: {document_id}")
        document = service.documents().get(documentId=document_id, includeTabsContent=True).execute()

        # --- IMPORTANT DEBUGGING LOGS ---
        app.logger.info(f"Document fetched. Top-level keys: {list(document.keys())}")

        if 'body' not in document:
            app.logger.error("Document object missing 'body' key.")
            app.logger.error(f"Full document response (first 500 chars): {json.dumps(document, indent=2)[:500]}...")
            raise KeyError("Document response is missing the 'body' key. Check document permissions or structure.")

        if 'content' not in document['body']:
            app.logger.error("Document 'body' object missing 'content' key.")
            app.logger.error(f"Full document body response (first 500 chars): {json.dumps(document['body'], indent=2)[:500]}...")
            raise KeyError("Document 'body' is missing the 'content' key. Check document structure.")
        # --- END DEBUGGING LOGS ---

        parsed_data = {
            "title": document.get('title', 'Untitled Document'),
            "books": []
        }

        doc_tabs = []
        if 'documentStyle' in document and 'documentTabProperties' in document['documentStyle']:
            doc_tabs = document['documentStyle']['documentTabProperties']

        if not doc_tabs:
            app.logger.warning("No DocumentTabProperties found. Processing as a single 'Main Document'.")
            parsed_data['books'].append({
                "title": "Main Document",
                "id": "tab-main",
                "startIndex": 0,
                "endIndex": len(json.dumps(document)), # Placeholder, actual end index of doc body
                "chapters": []
            })
            current_tab_index = 0
        else:
            for i, tab in enumerate(doc_tabs):
                parsed_data['books'].append({
                    "title": tab.get('title', f"Tab {i+1}"),
                    "id": f"tab-{tab.get('title', f'tab_{i+1}').replace(' ', '_').lower()}",
                    "startIndex": tab['range']['startIndex'],
                    "endIndex": tab['range']['endIndex'],
                    "chapters": []
                })
            current_tab_index = -1

        current_chapter = None
        chapter_counter = 0

        for element in document['body']['content']:
            start_index = element.get('startIndex', 0)
            end_index = element.get('endIndex', 0)
            element_content_html = ""

            found_tab_for_element = False
            if doc_tabs:
                for i, book_entry in enumerate(parsed_data['books']):
                    if start_index >= book_entry['startIndex'] and start_index < book_entry['endIndex']:
                        current_tab_index = i
                        found_tab_for_element = True
                        break
            elif parsed_data['books']:
                current_tab_index = 0
                found_tab_for_element = True

            if not found_tab_for_element:
                continue

            if 'paragraph' in element:
                paragraph = element['paragraph']
                named_style_type = paragraph.get('paragraphStyle', {}).get('namedStyleType')
                text_run_content = extract_text_from_elements([element])

                if named_style_type == 'HEADING_1':
                    if current_chapter:
                        parsed_data['books'][current_tab_index]['chapters'].append(current_chapter)
                    chapter_counter += 1
                    current_chapter = {
                        "number": text_run_content.strip(),
                        "title": "",
                        "content": "",
                        "id": f"chapter-{chapter_counter}"
                    }
                elif named_style_type == 'SUBTITLE':
                    if current_chapter and not current_chapter['title']:
                        current_chapter['title'] = text_run_content.strip()
                    else:
                        if current_chapter:
                            current_chapter['content'] += text_run_content
                        else:
                            pass
                else:
                    if current_chapter:
                        current_chapter['content'] += text_run_content
                    else:
                        if parsed_data['books'][current_tab_index]['chapters']:
                            parsed_data['books'][current_tab_index]['chapters'][0]['content'] += text_run_content
                        else:
                            if not current_chapter:
                                chapter_counter += 1
                                current_chapter = {
                                    "number": "0",
                                    "title": "Introduction",
                                    "content": "",
                                    "id": f"chapter-{chapter_counter}"
                                }
                                parsed_data['books'][current_tab_index]['chapters'].append(current_chapter)
                            current_chapter['content'] += text_run_content
            else:
                element_text = extract_text_from_elements([element])
                if current_chapter:
                    current_chapter['content'] += element_text
                elif parsed_data['books'][current_tab_index]['chapters']:
                    parsed_data['books'][current_tab_index]['chapters'][0]['content'] += element_text
                else:
                    if not current_chapter:
                        chapter_counter += 1
                        current_chapter = {
                            "number": "0",
                            "title": "Introduction",
                            "content": "",
                            "id": f"chapter-{chapter_counter}"
                        }
                        parsed_data['books'][current_tab_index]['chapters'].append(current_chapter)
                    current_chapter['content'] += element_text

        if current_chapter and current_tab_index != -1:
            parsed_data['books'][current_tab_index]['chapters'].append(current_chapter)

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
