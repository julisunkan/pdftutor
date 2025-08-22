import os
import logging
import json
import base64
from io import BytesIO
from flask import Flask, render_template, request, jsonify, send_from_directory, session, redirect, url_for, flash
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
import pdfplumber
import fitz  # PyMuPDF
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
ALLOWED_EXTENSIONS = {'pdf'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['EXTRACTED_FOLDER'] = EXTRACTED_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(EXTRACTED_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
                'images': [],
                'tables': [],
                'bbox': page.bbox
            }
            
            # Extract text with error handling
            try:
                text = page.extract_text()
                if text:
                    page_content['text'] = text.strip()
            except Exception as e:
                logging.warning(f"Could not extract text from page {i+1}: {e}")
                page_content['text'] = f"[Text extraction failed for page {i+1}]"
            
            # Extract tables with error handling
            try:
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        if table:  # Skip empty tables
                            page_content['tables'].append(table)
            except Exception as e:
                logging.warning(f"Could not extract tables from page {i+1}: {e}")
            
            # Extract images with error handling
            try:
                if hasattr(page, 'images') and page.images:
                    for img_idx, img in enumerate(page.images):
                        try:
                            # Extract image data
                            img_obj = page.crop(img['bbox']).to_image()
                            img_path = os.path.join(EXTRACTED_FOLDER, f'page_{i+1}_img_{img_idx}.png')
                            img_obj.save(img_path)
                            
                            page_content['images'].append({
                                'path': img_path,
                                'bbox': img['bbox'],
                                'index': img_idx
                            })
                        except Exception as e:
                            logging.warning(f"Error extracting image {img_idx} from page {i+1}: {e}")
            except Exception as e:
                logging.warning(f"Error processing images on page {i+1}: {e}")
            
            content['pages'].append(page_content)
    
    return content

def extract_pdf_content_pymupdf(pdf_path):
    """Extract PDF content using PyMuPDF as fallback"""
    content = {
        'pages': [],
        'total_pages': 0,
        'title': '',
        'metadata': {}
    }
    
    doc = fitz.open(pdf_path)
    content['total_pages'] = doc.page_count
    content['metadata'] = doc.metadata
    content['title'] = content['metadata'].get('title', 'PDF Tutorial') or 'PDF Tutorial'
    
    for i in range(doc.page_count):
        page = doc[i]
        page_content = {
            'page_number': i + 1,
            'text': '',
            'images': [],
            'tables': [],
            'bbox': page.rect
        }
        
        # Extract text
        try:
            text = page.get_text()
            if text:
                page_content['text'] = text.strip()
        except Exception as e:
            logging.warning(f"Could not extract text from page {i+1}: {e}")
            page_content['text'] = f"[Text extraction failed for page {i+1}]"
        
        # Extract images
        try:
            image_list = page.get_images()
            for img_idx, img in enumerate(image_list):
                try:
                    xref = img[0]
                    pix = fitz.Pixmap(doc, xref)
                    if pix.n < 5:  # GRAY or RGB
                        img_path = os.path.join(EXTRACTED_FOLDER, f'page_{i+1}_img_{img_idx}.png')
                        pix.save(img_path)
                        page_content['images'].append({
                            'path': img_path,
                            'bbox': [0, 0, pix.width, pix.height],
                            'index': img_idx
                        })
                    pix = None
                except Exception as e:
                    logging.warning(f"Error extracting image {img_idx} from page {i+1}: {e}")
        except Exception as e:
            logging.warning(f"Error processing images on page {i+1}: {e}")
        
        content['pages'].append(page_content)
    
    doc.close()
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
    if 'current_pdf' in session and 'pdf_content' in session:
        return render_template('index.html', 
                             pdf_content=session['pdf_content'],
                             current_page=session.get('current_page', 1))
    return render_template('index.html', pdf_content=None)

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle PDF file upload"""
    if 'file' not in request.files:
        flash('No file selected', 'error')
        return redirect(url_for('index'))
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('index'))
    
    if file and allowed_file(file.filename):
        try:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            # Extract PDF content
            pdf_content = extract_pdf_content(filepath)
            
            # Store in session
            session['current_pdf'] = filename
            session['pdf_content'] = pdf_content
            session['current_page'] = 1
            
            flash(f'Successfully loaded: {pdf_content["title"]}', 'success')
            return redirect(url_for('index'))
            
        except Exception as e:
            logging.error(f"Error processing upload: {e}")
            flash(f'Error processing PDF: {str(e)}', 'error')
            return redirect(url_for('index'))
    else:
        flash('Invalid file type. Please upload a PDF file.', 'error')
        return redirect(url_for('index'))

@app.route('/api/page/<int:page_num>')
def get_page(page_num):
    """Get specific page content"""
    if 'pdf_content' not in session:
        return jsonify({'error': 'No PDF loaded'}), 400
    
    pdf_content = session['pdf_content']
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
    if not query or 'pdf_content' not in session:
        return jsonify({'results': []})
    
    pdf_content = session['pdf_content']
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
