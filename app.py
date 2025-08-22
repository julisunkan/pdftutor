import os
import logging
import json
import base64
import pickle
import hashlib
from io import BytesIO
from flask import Flask, render_template, request, jsonify, send_from_directory, session, redirect, url_for, flash
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
import pdfplumber
try:
    import fitz  # PyMuPDF
except ImportError:
    try:
        import pymupdf as fitz  # Alternative import
    except ImportError:
        fitz = None  # PyMuPDF not available
from PIL import Image

# Configure logging with reduced verbosity
logging.basicConfig(level=logging.INFO)
# Reduce pdfminer logging to prevent conflicts
logging.getLogger('pdfminer').setLevel(logging.WARNING)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-in-production")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Configuration
UPLOAD_FOLDER = 'static/uploads'
EXTRACTED_FOLDER = 'static/extracted'
DATA_FOLDER = 'static/data'
ALLOWED_EXTENSIONS = {'pdf'}
MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB max file size

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['EXTRACTED_FOLDER'] = EXTRACTED_FOLDER
app.config['DATA_FOLDER'] = DATA_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(EXTRACTED_FOLDER, exist_ok=True)
os.makedirs(DATA_FOLDER, exist_ok=True)

@app.errorhandler(500)
def internal_error(error):
    """Handle internal server errors"""
    logging.error(f"Internal server error: {error}")
    flash('An internal error occurred while processing your request. Please try again.', 'error')
    return redirect(url_for('index'))

@app.errorhandler(413)
def too_large(error):
    """Handle file too large errors"""
    logging.error(f"File too large: {error}")
    flash('File too large. Please upload a file smaller than 500MB.', 'error')
    return redirect(url_for('index'))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_pdf_data(pdf_content, filename):
    """Save PDF content to disk and return an ID for session storage"""
    # Create a unique ID for this PDF
    pdf_id = hashlib.md5(f"{filename}_{len(pdf_content['pages'])}_{pdf_content['total_pages']}".encode()).hexdigest()
    
    # Save to disk
    data_path = os.path.join(app.config['DATA_FOLDER'], f'{pdf_id}.pkl')
    with open(data_path, 'wb') as f:
        pickle.dump(pdf_content, f)
    
    return pdf_id

def load_pdf_data(pdf_id):
    """Load PDF content from disk using ID"""
    data_path = os.path.join(app.config['DATA_FOLDER'], f'{pdf_id}.pkl')
    if not os.path.exists(data_path):
        return None
    
    try:
        with open(data_path, 'rb') as f:
            return pickle.load(f)
    except Exception as e:
        logging.error(f"Error loading PDF data: {e}")
        return None

def is_blank_page(page_content):
    """Determine if a page is considered blank/empty"""
    text = page_content.get('text', '').strip()
    images = page_content.get('images', [])
    tables = page_content.get('tables', [])
    
    # Check for structured content
    elements = page_content.get('elements', [])
    structured_text = page_content.get('structured_text', [])
    
    # Page is blank if:
    # 1. No images, tables, or structured elements
    # 2. Text is empty or very minimal (less than 20 chars, likely just page numbers)
    # 3. No elements in the structured layout
    
    has_content_elements = len(elements) > 0
    has_structured_text = len(structured_text) > 0
    has_media = bool(images or tables)
    has_substantial_text = text and len(text) > 20
    
    has_content = has_content_elements or has_structured_text or has_media or has_substantial_text
    
    return not has_content

def extract_pdf_content_pdfplumber(pdf_path):
    """Extract PDF content using pdfplumber"""
    content = {
        'pages': [],
        'total_pages': 0,
        'title': '',
        'metadata': {}
    }
    
    with pdfplumber.open(pdf_path) as pdf:
        content['total_pages'] = len(pdf.pages)
        content['metadata'] = pdf.metadata or {}
        content['title'] = content['metadata'].get('Title', 'PDF Tutorial')
        
        for i, page in enumerate(pdf.pages):
            page_content = {
                'page_number': i + 1,
                'text': '',
                'structured_text': [],
                'images': [],
                'tables': [],
                'bbox': page.bbox,
                'elements': []  # Combined ordered elements for layout preservation
            }
            
            # Extract text with better formatting preservation
            try:
                # Extract plain text
                text = page.extract_text()
                if text:
                    page_content['text'] = text.strip()
                
                # Extract structured text with positioning
                chars = page.chars
                if chars:
                    # Group characters into text blocks
                    text_blocks = []
                    current_block = {'text': '', 'bbox': None, 'fontsize': None}
                    
                    for char in chars:
                        if current_block['text'] and (
                            abs(char.get('size', 0) - (current_block['fontsize'] or 0)) > 2 or
                            char.get('top', 0) > (current_block['bbox'][3] if current_block['bbox'] else 0) + 10
                        ):
                            if current_block['text'].strip():
                                text_blocks.append(current_block)
                            current_block = {'text': '', 'bbox': None, 'fontsize': None}
                        
                        current_block['text'] += char.get('text', '')
                        if not current_block['bbox']:
                            current_block['bbox'] = [char.get('x0', 0), char.get('top', 0), char.get('x1', 0), char.get('bottom', 0)]
                            current_block['fontsize'] = char.get('size', 12)
                        else:
                            current_block['bbox'][2] = max(current_block['bbox'][2], char.get('x1', 0))
                            current_block['bbox'][3] = max(current_block['bbox'][3], char.get('bottom', 0))
                    
                    if current_block['text'].strip():
                        text_blocks.append(current_block)
                    
                    page_content['structured_text'] = text_blocks
                    
                    # Add text blocks to elements list for ordering
                    for block in text_blocks:
                        page_content['elements'].append({
                            'type': 'text',
                            'content': block,
                            'position': block['bbox'][1] if block['bbox'] else 0
                        })
            except Exception as e:
                logging.warning(f"Could not extract text from page {i+1}: {e}")
                page_content['text'] = f"[Text extraction failed for page {i+1}]"
            
            # Extract tables with enhanced formatting
            try:
                tables = page.extract_tables()
                if tables:
                    for table_idx, table in enumerate(tables):
                        if table and len(table) > 0:  # Skip empty tables
                            # Get table settings for better formatting
                            table_settings = {
                                'vertical_strategy': 'lines',
                                'horizontal_strategy': 'lines'
                            }
                            
                            # Try to get table with settings
                            try:
                                formatted_table = page.extract_table(table_settings)
                                if formatted_table:
                                    table = formatted_table
                            except:
                                pass
                            
                            # Find table position
                            table_bbox = None
                            try:
                                # Estimate table position from first and last cells
                                if hasattr(page, 'crop'):
                                    try:
                                        table_objects = list(page.filter(lambda x: x.get('object_type') == 'rect'))
                                        if table_objects:
                                            table_bbox = [min(obj['x0'] for obj in table_objects),
                                                        min(obj['top'] for obj in table_objects),
                                                        max(obj['x1'] for obj in table_objects),
                                                        max(obj['bottom'] for obj in table_objects)]
                                    except:
                                        table_bbox = [0, 0, page.width, 50]
                            except:
                                table_bbox = [0, 0, page.width, 50]  # Default position
                            
                            table_data = {
                                'data': table,
                                'bbox': table_bbox,
                                'index': table_idx
                            }
                            page_content['tables'].append(table_data)
                            
                            # Add table to elements list for ordering
                            page_content['elements'].append({
                                'type': 'table',
                                'content': table_data,
                                'position': table_bbox[1] if table_bbox else 0
                            })
            except Exception as e:
                logging.warning(f"Could not extract tables from page {i+1}: {e}")
            
            # Extract images with enhanced positioning
            try:
                if hasattr(page, 'images') and page.images:
                    for img_idx, img in enumerate(page.images):
                        try:
                            # Ensure bbox exists
                            bbox = img.get('bbox')
                            if not bbox:
                                logging.warning(f"No bbox for image {img_idx} on page {i+1}")
                                continue
                                
                            # Extract image data with better quality
                            img_obj = page.crop(bbox).to_image(resolution=150)  # Higher resolution
                            img_path = os.path.join(EXTRACTED_FOLDER, f'page_{i+1}_img_{img_idx}.png')
                            img_obj.save(img_path, format='PNG', optimize=True)
                            
                            image_data = {
                                'path': img_path,
                                'bbox': bbox,
                                'index': img_idx,
                                'width': bbox[2] - bbox[0],
                                'height': bbox[3] - bbox[1]
                            }
                            page_content['images'].append(image_data)
                            
                            # Add image to elements list for ordering
                            page_content['elements'].append({
                                'type': 'image',
                                'content': image_data,
                                'position': bbox[1]
                            })
                        except Exception as e:
                            logging.warning(f"Error extracting image {img_idx} from page {i+1}: {e}")
            except Exception as e:
                logging.warning(f"Error processing images on page {i+1}: {e}")
            
            # Sort elements by position for proper layout
            page_content['elements'].sort(key=lambda x: x['position'])
            
            # Only add page if it's not blank
            if not is_blank_page(page_content):
                content['pages'].append(page_content)
            else:
                logging.info(f"Skipping blank page {i+1}")
    
    # Renumber pages after filtering
    for idx, page in enumerate(content['pages']):
        page['page_number'] = idx + 1
    
    # Update total pages count
    content['total_pages'] = len(content['pages'])
    
    return content

def extract_pdf_content_pymupdf(pdf_path):
    """Extract PDF content using PyMuPDF as fallback"""
    if fitz is None:
        raise ImportError("PyMuPDF (fitz) is not available")
        
    content = {
        'pages': [],
        'total_pages': 0,
        'title': '',
        'metadata': {}
    }
    
    doc = fitz.open(pdf_path)
    content['total_pages'] = doc.page_count
    content['metadata'] = doc.metadata or {}
    content['title'] = content['metadata'].get('title', 'PDF Tutorial') or 'PDF Tutorial'
    
    for i in range(doc.page_count):
        page = doc[i]
        page_content = {
            'page_number': i + 1,
            'text': '',
            'structured_text': [],
            'images': [],
            'tables': [],
            'bbox': page.rect,
            'elements': []
        }
        
        # Extract text with structure
        try:
            text = page.get_text()
            if text:
                page_content['text'] = text.strip()
            
            # Extract text blocks with formatting
            text_blocks = page.get_text("dict")
            if text_blocks and 'blocks' in text_blocks:
                for block in text_blocks['blocks']:
                    if 'lines' in block:
                        for line in block['lines']:
                            if 'spans' in line:
                                line_text = ''.join(span.get('text', '') for span in line['spans'])
                                if line_text.strip():
                                    text_block = {
                                        'text': line_text,
                                        'bbox': line.get('bbox', [0, 0, 0, 0]),
                                        'fontsize': line['spans'][0].get('size', 12) if line['spans'] else 12
                                    }
                                    page_content['structured_text'].append(text_block)
                                    page_content['elements'].append({
                                        'type': 'text',
                                        'content': text_block,
                                        'position': text_block['bbox'][1]
                                    })
        except Exception as e:
            logging.warning(f"Could not extract text from page {i+1}: {e}")
            page_content['text'] = f"[Text extraction failed for page {i+1}]"
        
        # Extract images with positioning
        try:
            image_list = page.get_images(full=True)
            for img_idx, img in enumerate(image_list):
                try:
                    xref = img[0]
                    pix = fitz.Pixmap(doc, xref)
                    
                    if pix.n < 5:  # GRAY or RGB
                        img_path = os.path.join(EXTRACTED_FOLDER, f'page_{i+1}_img_{img_idx}.png')
                        pix.save(img_path)
                        
                        # Try to get image position
                        img_rects = page.get_image_rects(xref)
                        img_bbox = img_rects[0] if img_rects else [0, 0, pix.width, pix.height]
                        
                        image_data = {
                            'path': img_path,
                            'bbox': img_bbox,
                            'index': img_idx,
                            'width': pix.width,
                            'height': pix.height
                        }
                        page_content['images'].append(image_data)
                        page_content['elements'].append({
                            'type': 'image',
                            'content': image_data,
                            'position': img_bbox[1] if img_bbox else 0
                        })
                    pix = None
                except Exception as e:
                    logging.warning(f"Error extracting image {img_idx} from page {i+1}: {e}")
        except Exception as e:
            logging.warning(f"Error processing images on page {i+1}: {e}")
        
        # Sort elements by position for proper layout
        page_content['elements'].sort(key=lambda x: x['position'])
        
        # Only add page if it's not blank
        if not is_blank_page(page_content):
            content['pages'].append(page_content)
        else:
            logging.info(f"Skipping blank page {i+1}")
    
    doc.close()
    
    # Renumber pages after filtering
    for idx, page in enumerate(content['pages']):
        page['page_number'] = idx + 1
    
    # Update total pages count
    content['total_pages'] = len(content['pages'])
    
    return content

def extract_pdf_content(pdf_path):
    """Extract text, images, and basic table data from PDF with fallback methods"""
    try:
        # Try pdfplumber first (better for tables and structured text)
        logging.info("Attempting PDF extraction with pdfplumber...")
        return extract_pdf_content_pdfplumber(pdf_path)
    except Exception as e:
        logging.warning(f"pdfplumber failed: {e}")
        try:
            # Fallback to PyMuPDF (more robust for problematic PDFs)
            logging.info("Falling back to PyMuPDF extraction...")
            return extract_pdf_content_pymupdf(pdf_path)
        except Exception as e2:
            logging.error(f"Both extraction methods failed. pdfplumber: {e}, PyMuPDF: {e2}")
            raise Exception(f"Failed to process PDF with both methods: pdfplumber ({str(e)}) and PyMuPDF ({str(e2)})")

@app.route('/')
def index():
    """Main page - show upload form or tutorial if PDF is in session"""
    if 'current_pdf' in session and 'pdf_id' in session:
        # Load minimal data needed for initial rendering
        pdf_metadata = session.get('pdf_metadata', {})
        if pdf_metadata:
            return render_template('index.html', 
                                 pdf_content=pdf_metadata,
                                 current_page=session.get('current_page', 1))
    return render_template('index.html', pdf_content=None)

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle PDF file upload"""
    try:
        if 'file' not in request.files:
            flash('No file selected', 'error')
            return redirect(url_for('index'))
        
        file = request.files['file']
        if not file or not file.filename or file.filename == '':
            flash('No file selected', 'error')
            return redirect(url_for('index'))
        
        if file and allowed_file(file.filename):
            try:
                filename = secure_filename(file.filename or 'unknown.pdf')
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                
                logging.info(f"Saving file to: {filepath}")
                file.save(filepath)
                
                # Check file size
                file_size = os.path.getsize(filepath)
                logging.info(f"Uploaded file size: {file_size} bytes")
                
                # Extract PDF content
                logging.info("Starting PDF content extraction...")
                pdf_content = extract_pdf_content(filepath)
                logging.info(f"Extracted {pdf_content['total_pages']} pages")
                
                # Save PDF data to disk and store only ID in session
                pdf_id = save_pdf_data(pdf_content, filename)
                session['current_pdf'] = filename
                session['pdf_id'] = pdf_id
                session['current_page'] = 1
                
                # Store basic metadata in session for UI
                session['pdf_metadata'] = {
                    'title': pdf_content['title'],
                    'total_pages': pdf_content['total_pages']
                }
                
                flash(f'Successfully loaded: {pdf_content["title"]}', 'success')
                return redirect(url_for('index'))
                
            except Exception as e:
                logging.error(f"Error processing upload: {e}")
                import traceback
                logging.error(f"Full traceback: {traceback.format_exc()}")
                flash(f'Error processing PDF: {str(e)}', 'error')
                return redirect(url_for('index'))
        else:
            flash('Invalid file type. Please upload a PDF file.', 'error')
            return redirect(url_for('index'))
    except Exception as e:
        logging.error(f"Error in upload_file function: {e}")
        import traceback
        logging.error(f"Full traceback: {traceback.format_exc()}")
        flash(f'Upload error: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/api/page/<int:page_num>')
def get_page(page_num):
    """Get specific page content"""
    if 'pdf_id' not in session:
        return jsonify({'error': 'No PDF loaded'}), 400
    
    # Load PDF content from disk
    pdf_content = load_pdf_data(session['pdf_id'])
    if not pdf_content:
        return jsonify({'error': 'PDF data not found'}), 400
    
    if page_num < 1 or page_num > pdf_content['total_pages']:
        return jsonify({'error': 'Invalid page number'}), 400
    
    page_content = pdf_content['pages'][page_num - 1]
    session['current_page'] = page_num
    
    return jsonify({
        'success': True,
        'page': page_content,
        'total_pages': pdf_content['total_pages'],
        'current_page': page_num
    })

@app.route('/api/search')
def search():
    """Search through PDF content"""
    query = request.args.get('q', '').strip().lower()
    if not query or 'pdf_id' not in session:
        return jsonify({'results': []})
    
    # Load PDF content from disk
    pdf_content = load_pdf_data(session['pdf_id'])
    if not pdf_content:
        return jsonify({'results': []})
    results = []
    
    for page in pdf_content['pages']:
        text = page['text'].lower()
        if query in text:
            # Find context around matches
            matches = []
            start = 0
            while True:
                pos = text.find(query, start)
                if pos == -1:
                    break
                
                # Get context (50 chars before and after)
                context_start = max(0, pos - 50)
                context_end = min(len(text), pos + len(query) + 50)
                context = page['text'][context_start:context_end]
                
                matches.append({
                    'position': pos,
                    'context': context,
                    'highlight_start': pos - context_start,
                    'highlight_end': pos - context_start + len(query)
                })
                start = pos + 1
            
            if matches:
                results.append({
                    'page_number': page['page_number'],
                    'matches': matches
                })
    
    return jsonify({'results': results})

@app.route('/api/bookmark', methods=['GET', 'POST'])
def bookmarks():
    """Handle bookmarks"""
    if request.method == 'POST':
        data = request.get_json()
        page_num = data.get('page_number')
        action = data.get('action', 'add')  # add or remove
        
        if 'bookmarks' not in session:
            session['bookmarks'] = []
        
        bookmarks = session['bookmarks']
        
        if action == 'add' and page_num not in bookmarks:
            bookmarks.append(page_num)
        elif action == 'remove' and page_num in bookmarks:
            bookmarks.remove(page_num)
        
        session['bookmarks'] = bookmarks
        session.modified = True
        
        return jsonify({'success': True, 'bookmarks': bookmarks})
    
    return jsonify({'bookmarks': session.get('bookmarks', [])})

@app.route('/api/notes', methods=['GET', 'POST'])
def notes():
    """Handle page notes"""
    if request.method == 'POST':
        data = request.get_json()
        page_num = data.get('page_number')
        note_text = data.get('note', '').strip()
        
        if 'notes' not in session:
            session['notes'] = {}
        
        notes = session['notes']
        
        if note_text:
            notes[str(page_num)] = note_text
        elif str(page_num) in notes:
            del notes[str(page_num)]
        
        session['notes'] = notes
        session.modified = True
        
        return jsonify({'success': True})
    
    return jsonify({'notes': session.get('notes', {})})

@app.route('/clear')
def clear_session():
    """Clear current PDF and session data"""
    session.clear()
    flash('Session cleared', 'info')
    return redirect(url_for('index'))

@app.errorhandler(413)
def too_large(e):
    flash('File too large. Maximum size is 16MB.', 'error')
    return redirect(url_for('index'))

@app.errorhandler(404)
def not_found(e):
    return render_template('index.html', pdf_content=None), 404

@app.errorhandler(500)
def server_error(e):
    logging.error(f"Server error: {e}")
    flash('An internal error occurred. Please try again.', 'error')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
