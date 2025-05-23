import os
import json
from flask import Flask, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapapiclient.errors import HttpError
from flask_cors import CORS # For allowing requests from your GoDaddy domain

app = Flask(__name__)
CORS(app) # Enable CORS for all routes

# --- Google Docs API Configuration ---
SCOPES = ['https://www.googleapis.com/auth/documents.readonly']
# The GOOGLE_APPLICATION_CREDENTIALS_JSON environment variable will hold the service account key
# Railway will inject this when deployed.

def get_docs_service():
    """Initializes and returns a Google Docs API service client."""
    try:
        # Load credentials from the environment variable
        creds_json = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON')
        if not creds_json:
            raise ValueError("GOOGLE_APPLICATION_CREDENTIALS_JSON environment variable not set.")

        info = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        service = build('docs', 'v1', credentials=credentials)
        return service
    except Exception as e:
        app.logger.error(f"Error initializing Google Docs service: {e}")
        raise

# --- Helper function to extract text from Google Docs content ---
# This is a simplified version, you might extend it based on your needs.
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
            # Basic table handling: concatenate text from cells
            for row in element['table']['tableRows']:
                for cell in row['tableCells']:
                    text_content += extract_text_from_elements(cell['content']) + " | "
            text_content += "\n"
        # Add other element types as needed (e.g., sectionBreak, inlineObjectElement)
    return text_content

# --- API Endpoint to Fetch Document Content ---
@app.route('/get-doc-content', methods=['GET'])
def get_document_content():
    document_id = request.args.get('document_id')
    if not document_id:
        return jsonify({"error": "Missing 'document_id' query parameter."}), 400

    try:
        service = get_docs_service()
        # Request document with includeTabsContent = True
        document = service.documents().get(documentId=document_id, includeTabsContent=True).execute()

        # --- Parse and Structure the Response ---
        parsed_data = {
            "title": document.get('title', 'Untitled Document'),
            "books": []
        }

        # Attempt to find DocumentTabProperties (your "Books")
        doc_tabs = []
        if 'documentStyle' in document and 'documentTabProperties' in document['documentStyle']:
            doc_tabs = document['documentStyle']['documentTabProperties']

        # If no API tabs, create a single "Main Document" entry
        if not doc_tabs:
            app.logger.warning("No DocumentTabProperties found. Processing as a single 'Main Document'.")
            parsed_data['books'].append({
                "title": "Main Document",
                "id": "tab-main",
                "startIndex": 0,
                "endIndex": len(json.dumps(document)), # Placeholder, actual end index of doc body
                "chapters": []
            })
            # For a single document, we'll process its entire body content
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
            current_tab_index = -1 # No active tab initially

        # Process document body content to map to tabs and chapters
        current_chapter = None
        chapter_counter = 0

        for element in document['body']['content']:
            start_index = element.get('startIndex', 0)
            end_index = element.get('endIndex', 0)
            element_content_html = "" # Placeholder for rich HTML conversion if needed

            # Identify which 'book' (tab) this element belongs to
            found_tab_for_element = False
            if doc_tabs:
                for i, book_entry in enumerate(parsed_data['books']):
                    if start_index >= book_entry['startIndex'] and start_index < book_entry['endIndex']:
                        current_tab_index = i
                        found_tab_for_element = True
                        break
            elif parsed_data['books']: # If only 'Main Document' book
                current_tab_index = 0
                found_tab_for_element = True

            if not found_tab_for_element:
                continue # Skip elements not within any defined tab/document range

            if 'paragraph' in element:
                paragraph = element['paragraph']
                named_style_type = paragraph.get('paragraphStyle', {}).get('namedStyleType')
                text_run_content = extract_text_from_elements([element]) # Extract text

                if named_style_type == 'HEADING_1':
                    if current_chapter:
                        parsed_data['books'][current_tab_index]['chapters'].append(current_chapter)
                    chapter_counter += 1
                    current_chapter = {
                        "number": text_run_content.strip(),
                        "title": "", # Will be filled by SUBTITLE
                        "content": "",
                        "id": f"chapter-{chapter_counter}"
                    }
                elif named_style_type == 'SUBTITLE':
                    if current_chapter and not current_chapter['title']: # Only set if not already set
                        current_chapter['title'] = text_run_content.strip()
                    else:
                        # If subtitle without H1 or after title, treat as regular content
                        if current_chapter:
                            current_chapter['content'] += text_run_content # Append as raw text
                        else:
                            # If no chapter, add to the first chapter of the current book if it exists
                            pass # This case might need specific handling based on doc structure
                else:
                    # Other paragraph types are content
                    if current_chapter:
                        current_chapter['content'] += text_run_content # Append as raw text
                    else:
                        # If no chapter yet (e.g., intro content before first H1), handle as part of the first chapter
                        # or create a dummy initial chapter. For now, we'll append to the first chapter if it exists.
                        if parsed_data['books'][current_tab_index]['chapters']:
                            parsed_data['books'][current_tab_index]['chapters'][0]['content'] += text_run_content
                        else:
                            # If no chapters at all, create a default chapter for general content
                            if not current_chapter:
                                chapter_counter += 1
                                current_chapter = {
                                    "number": "0", # No explicit number
                                    "title": "Introduction",
                                    "content": "",
                                    "id": f"chapter-{chapter_counter}"
                                }
                                parsed_data['books'][current_tab_index]['chapters'].append(current_chapter)
                            current_chapter['content'] += text_run_content


            else:
                # Handle non-paragraph elements (e.g., tables, section breaks, images)
                # For simplicity, just append their raw text content.
                # A more advanced parser would convert these to HTML.
                element_text = extract_text_from_elements([element])
                if current_chapter:
                    current_chapter['content'] += element_text
                elif parsed_data['books'][current_tab_index]['chapters']:
                    parsed_data['books'][current_tab_index]['chapters'][0]['content'] += element_text
                else:
                    # If no chapters at all, create a default chapter for general content
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


        # Append the last active chapter to its respective book
        if current_chapter and current_tab_index != -1:
            parsed_data['books'][current_tab_index]['chapters'].append(current_chapter)

        # Filter out any books without chapters if that makes sense for your structure
        parsed_data['books'] = [book for book in parsed_data['books'] if book['chapters']]


        return jsonify(parsed_data)

    except HttpError as e:
        app.logger.error(f"Google API Error: {e.status_code} - {e.reason}")
        return jsonify({"error": f"Google API Error: {e.reason}", "code": e.status_code}), e.status_code
    except ValueError as e:
        app.logger.error(f"Configuration Error: {e}")
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        app.logger.error(f"An unexpected error occurred: {e}")
        return jsonify({"error": f"An unexpected server error occurred: {e}"}), 500

if __name__ == '__main__':
    # For local testing, you might set a dummy env var
    # os.environ['GOOGLE_APPLICATION_CREDENTIALS_JSON'] = json.dumps({"your_sa_key": "here"})
    # app.run(debug=True, port=5000)
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
