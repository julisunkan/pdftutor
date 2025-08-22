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
logging.getLogger('pdfplumber').setLevel(logging.WARNING)
logging.getLogger('PIL').setLevel(logging.WARNING)

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

def convert_pdf_to_images(pdf_path):
    """Convert PDF pages to images - much faster than text extraction"""
    content = {
        'pages': [],
        'total_pages': 0,
        'title': '',
        'metadata': {}
    }
    
    try:
        # Try using pdf2image first (fast and reliable)
        from pdf2image import convert_from_path
        
        # Get PDF metadata
        with pdfplumber.open(pdf_path) as pdf:
            content['metadata'] = pdf.metadata or {}
            content['title'] = content['metadata'].get('Title', 'PDF Tutorial')
            content['total_pages'] = len(pdf.pages)
        
        logging.info(f"Converting {content['total_pages']} pages to images...")
        
        # Convert PDF to images with optimized settings
        dpi = 150 if content['total_pages'] < 200 else 100  # Lower DPI for large files
        
        # Process in batches to manage memory
        batch_size = 50 if content['total_pages'] > 200 else 100
        
        for start_page in range(0, content['total_pages'], batch_size):
            end_page = min(start_page + batch_size, content['total_pages'])
            logging.info(f"Processing pages {start_page + 1}-{end_page}...")
            
            try:
                images = convert_from_path(
                    pdf_path,
                    dpi=dpi,
                    first_page=start_page + 1,
                    last_page=end_page,
                    fmt='JPEG',
                    jpegopt={'quality': 85, 'progressive': True, 'optimize': True}
                )
                
                for i, image in enumerate(images):
                    page_num = start_page + i + 1
                    img_path = os.path.join(EXTRACTED_FOLDER, f'page_{page_num}.jpg')
                    
                    # Save optimized image
                    image.save(img_path, 'JPEG', quality=85, optimize=True)
                    
                    page_content = {
                        'page_number': page_num,
                        'image_path': img_path,
                        'width': image.width,
                        'height': image.height,
                        'text': '',  # Keep for search functionality if needed
                        'type': 'image'
                    }
                    content['pages'].append(page_content)
                    
            except Exception as e:
                logging.error(f"Error converting pages {start_page + 1}-{end_page}: {e}")
                # Continue with next batch
                continue
        
        content['total_pages'] = len(content['pages'])
        logging.info(f"Successfully converted {content['total_pages']} pages to images")
        return content
        
    except ImportError:
        logging.warning("pdf2image not available, falling back to PyMuPDF")
        return convert_pdf_to_images_pymupdf(pdf_path)
    except Exception as e:
        logging.error(f"pdf2image failed: {e}, falling back to PyMuPDF")
        return convert_pdf_to_images_pymupdf(pdf_path)

def convert_pdf_to_images_pymupdf(pdf_path):
    """Convert PDF to images using PyMuPDF as fallback"""
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
    
    logging.info(f"Converting {content['total_pages']} pages to images using PyMuPDF...")
    
    # Optimize matrix for different file sizes
    zoom = 1.5 if content['total_pages'] < 200 else 1.0  # Lower zoom for large files
    mat = fitz.Matrix(zoom, zoom)
    
    for i in range(doc.page_count):
        if i % 50 == 0:
            logging.info(f"Converting page {i+1}/{content['total_pages']}")
            
        try:
            page = doc[i]
            pix = page.get_pixmap(matrix=mat)
            
            img_path = os.path.join(EXTRACTED_FOLDER, f'page_{i+1}.jpg')
            pix.save(img_path, output='jpg', jpg_quality=85)
            
            page_content = {
                'page_number': i + 1,
                'image_path': img_path,
                'width': pix.width,
                'height': pix.height,
                'text': '',
                'type': 'image'
            }
            content['pages'].append(page_content)
            pix = None  # Free memory
            
        except Exception as e:
            logging.warning(f"Error converting page {i+1}: {e}")
            continue
    
    doc.close()
    content['total_pages'] = len(content['pages'])
    logging.info(f"Successfully converted {content['total_pages']} pages to images")
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
    """Convert PDF pages to images for fast loading"""
    return convert_pdf_to_images(pdf_path)

def extract_pdf_content_with_progress(pdf_path):
    """Convert PDF pages to images with progress tracking"""
    try:
        # Try using pdf2image first (fast and reliable)
        from pdf2image import convert_from_path
        
        content = {
            'pages': [],
            'total_pages': 0,
            'title': '',
            'metadata': {}
        }
        
        # Get PDF metadata
        with pdfplumber.open(pdf_path) as pdf:
            content['metadata'] = pdf.metadata or {}
            content['title'] = content['metadata'].get('Title', 'PDF Tutorial')
            content['total_pages'] = len(pdf.pages)
        
        # Update progress
        session['conversion_progress']['percent'] = 20
        session['conversion_progress']['message'] = f'Converting {content["total_pages"]} pages to images...'
        session['conversion_progress']['details'] = f'Processing {content["total_pages"]} pages'
        session.modified = True
        
        logging.info(f"Converting {content['total_pages']} pages to images...")
        
        # Convert PDF to images with optimized settings
        dpi = 150 if content['total_pages'] < 200 else 100  # Lower DPI for large files
        
        # Process in batches to manage memory
        batch_size = 50 if content['total_pages'] > 200 else 100
        
        for start_page in range(0, content['total_pages'], batch_size):
            end_page = min(start_page + batch_size, content['total_pages'])
            
            # Update progress
            progress_percent = 20 + int((start_page / content['total_pages']) * 65)  # 20-85%
            session['conversion_progress']['percent'] = progress_percent
            session['conversion_progress']['message'] = f'Converting pages {start_page + 1}-{end_page}...'
            session['conversion_progress']['details'] = f'Batch {start_page//batch_size + 1} of {(content["total_pages"] + batch_size - 1)//batch_size}'
            session.modified = True
            
            logging.info(f"Processing pages {start_page + 1}-{end_page}...")
            
            try:
                images = convert_from_path(
                    pdf_path,
                    dpi=dpi,
                    first_page=start_page + 1,
                    last_page=end_page,
                    fmt='JPEG',
                    jpegopt={'quality': 85, 'progressive': True, 'optimize': True}
                )
                
                for i, image in enumerate(images):
                    page_num = start_page + i + 1
                    img_path = os.path.join(EXTRACTED_FOLDER, f'page_{page_num}.jpg')
                    
                    # Save optimized image
                    image.save(img_path, 'JPEG', quality=85, optimize=True)
                    
                    page_content = {
                        'page_number': page_num,
                        'image_path': img_path,
                        'width': image.width,
                        'height': image.height,
                        'text': '',  # Keep for search functionality if needed
                        'type': 'image'
                    }
                    content['pages'].append(page_content)
                    
            except Exception as e:
                logging.error(f"Error converting pages {start_page + 1}-{end_page}: {e}")
                # Continue with next batch
                continue
        
        content['total_pages'] = len(content['pages'])
        
        # Update final progress
        session['conversion_progress']['percent'] = 85
        session['conversion_progress']['message'] = f'Successfully converted {content["total_pages"]} pages'
        session.modified = True
        
        logging.info(f"Successfully converted {content['total_pages']} pages to images")
        return content
        
    except ImportError:
        logging.warning("pdf2image not available, falling back to PyMuPDF")
        return convert_pdf_to_images_pymupdf_with_progress(pdf_path)
    except Exception as e:
        logging.error(f"pdf2image failed: {e}, falling back to PyMuPDF")
        return convert_pdf_to_images_pymupdf_with_progress(pdf_path)

def convert_pdf_to_images_pymupdf_with_progress(pdf_path):
    """Convert PDF to images using PyMuPDF with progress tracking"""
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
    
    # Update progress
    session['conversion_progress']['percent'] = 25
    session['conversion_progress']['message'] = f'Converting {content["total_pages"]} pages using fallback method...'
    session.modified = True
    
    logging.info(f"Converting {content['total_pages']} pages to images using PyMuPDF...")
    
    # Optimize matrix for different file sizes
    zoom = 1.5 if content['total_pages'] < 200 else 1.0  # Lower zoom for large files
    mat = fitz.Matrix(zoom, zoom)
    
    for i in range(doc.page_count):
        # Update progress every 50 pages
        if i % 50 == 0:
            progress_percent = 25 + int((i / content['total_pages']) * 60)  # 25-85%
            session['conversion_progress']['percent'] = progress_percent
            session['conversion_progress']['message'] = f'Converting page {i+1}/{content["total_pages"]}'
            session.modified = True
            logging.info(f"Converting page {i+1}/{content['total_pages']}")
            
        try:
            page = doc[i]
            pix = page.get_pixmap(matrix=mat)
            
            img_path = os.path.join(EXTRACTED_FOLDER, f'page_{i+1}.jpg')
            pix.save(img_path, output='jpg', jpg_quality=85)
            
            page_content = {
                'page_number': i + 1,
                'image_path': img_path,
                'width': pix.width,
                'height': pix.height,
                'text': '',
                'type': 'image'
            }
            content['pages'].append(page_content)
            pix = None  # Free memory
            
        except Exception as e:
            logging.warning(f"Error converting page {i+1}: {e}")
            continue
    
    doc.close()
    content['total_pages'] = len(content['pages'])
    
    # Update final progress
    session['conversion_progress']['percent'] = 85
    session['conversion_progress']['message'] = f'Successfully converted {content["total_pages"]} pages'
    session.modified = True
    
    logging.info(f"Successfully converted {content['total_pages']} pages to images")
    return content

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
                
                # Initialize progress tracking
                session['conversion_progress'] = {
                    'status': 'uploading',
                    'percent': 0,
                    'message': 'Uploading file...',
                    'details': ''
                }
                session.modified = True
                
                logging.info(f"Saving file to: {filepath}")
                file.save(filepath)
                
                # Update progress
                session['conversion_progress']['status'] = 'processing'
                session['conversion_progress']['percent'] = 10
                session['conversion_progress']['message'] = 'File uploaded, starting conversion...'
                session.modified = True
                
                # Check file size
                file_size = os.path.getsize(filepath)
                logging.info(f"Uploaded file size: {file_size} bytes")
                
                # Extract PDF content with progress updates
                logging.info("Starting PDF content extraction...")
                pdf_content = extract_pdf_content_with_progress(filepath)
                logging.info(f"Extracted {pdf_content['total_pages']} pages")
                
                # Update progress
                session['conversion_progress']['status'] = 'saving'
                session['conversion_progress']['percent'] = 90
                session['conversion_progress']['message'] = 'Saving processed data...'
                session.modified = True
                
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
                
                # Mark conversion complete
                session['conversion_progress']['status'] = 'complete'
                session['conversion_progress']['percent'] = 100
                session['conversion_progress']['message'] = 'Conversion complete!'
                session.modified = True
                
                flash(f'Successfully loaded: {pdf_content["title"]}', 'success')
                return redirect(url_for('index'))
                
            except Exception as e:
                session['conversion_progress'] = {
                    'status': 'error',
                    'percent': 0,
                    'message': f'Error: {str(e)}',
                    'details': ''
                }
                session.modified = True
                logging.error(f"Error processing upload: {e}")
                import traceback
                logging.error(f"Full traceback: {traceback.format_exc()}")
                flash(f'Error processing PDF: {str(e)}', 'error')
                return redirect(url_for('index'))
        else:
            flash('Invalid file type. Please upload a PDF file.', 'error')
            return redirect(url_for('index'))
    except Exception as e:
        session['conversion_progress'] = {
            'status': 'error',
            'percent': 0,
            'message': f'Upload error: {str(e)}',
            'details': ''
        }
        session.modified = True
        logging.error(f"Error in upload_file function: {e}")
        import traceback
        logging.error(f"Full traceback: {traceback.format_exc()}")
        flash(f'Upload error: {str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/api/page/<int:page_num>')
def get_page(page_num):
    """Get specific page image"""
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
    
    # Convert absolute path to relative path for serving
    if isinstance(page_content, dict):
        image_path = page_content.get('image_path', '')
    else:
        image_path = f"extracted/page_{page_num}.jpg"
    if image_path:
        if image_path.startswith('static/'):
            image_path = image_path.replace('static/', '')
        else:
            image_path = f"extracted/{os.path.basename(image_path)}"
    else:
        image_path = f"extracted/page_{page_num}.jpg"
    
    return jsonify({
        'success': True,
        'page': {
            'page_number': page_content['page_number'],
            'image_url': f'/static/{image_path}',
            'width': page_content['width'],
            'height': page_content['height'],
            'type': 'image'
        },
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

@app.route('/api/progress')
def get_progress():
    """Get current conversion progress"""
    progress = session.get('conversion_progress', {
        'status': 'idle',
        'percent': 0,
        'message': 'Ready',
        'details': ''
    })
    return jsonify(progress)

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
