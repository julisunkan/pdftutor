// PDF Tutorial App JavaScript
class PDFTutorialApp {
    constructor() {
        this.currentPage = window.pdfData ? window.pdfData.currentPage : 1;
        this.totalPages = window.pdfData ? window.pdfData.totalPages : 0;
        this.bookmarks = [];
        this.notes = {};
        this.searchResults = [];
        this.sidebarVisible = false;
        this.fabMenuOpen = false;
        
        this.init();
    }
    
    init() {
        this.bindEvents();
        this.loadInitialData();
        this.updateProgress();
        this.checkMobileLayout();
        
        // Load current page content if PDF is loaded
        if (this.totalPages > 0) {
            this.loadPage(this.currentPage);
            this.loadBookmarks();
            this.loadNotes();
        }
    }
    
    bindEvents() {
        // Navigation events
        document.getElementById('prevBtn')?.addEventListener('click', () => this.previousPage());
        document.getElementById('nextBtn')?.addEventListener('click', () => this.nextPage());
        document.getElementById('jumpBtn')?.addEventListener('click', () => this.jumpToPage());
        document.getElementById('jumpToPage')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.jumpToPage();
        });
        
        // Search events
        document.getElementById('searchInput')?.addEventListener('input', 
            this.debounce(() => this.performSearch(), 300));
        
        // Theme toggle
        document.getElementById('themeToggle')?.addEventListener('click', () => this.toggleTheme());
        
        // FAB events
        document.getElementById('fabMain')?.addEventListener('click', () => this.toggleFabMenu());
        document.getElementById('toggleBookmark')?.addEventListener('click', () => this.toggleBookmark());
        document.getElementById('toggleSidebar')?.addEventListener('click', () => this.toggleSidebar());
        document.getElementById('saveNote')?.addEventListener('click', () => this.saveNote());
        
        // Thumbnail navigation
        document.querySelectorAll('.thumbnail-item').forEach(thumb => {
            thumb.addEventListener('click', () => {
                const page = parseInt(thumb.dataset.page);
                this.goToPage(page);
            });
        });
        
        // Keyboard navigation
        document.addEventListener('keydown', (e) => this.handleKeyboardNavigation(e));
        
        // Touch gestures for mobile
        this.bindTouchEvents();
        
        // Window resize
        window.addEventListener('resize', () => this.checkMobileLayout());
        
        // Close FAB menu when clicking outside
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.fab-container') && this.fabMenuOpen) {
                this.closeFabMenu();
            }
        });
    }
    
    bindTouchEvents() {
        const pageContent = document.getElementById('pageContent');
        if (!pageContent) return;
        
        let startX = 0;
        let startY = 0;
        let endX = 0;
        let endY = 0;
        
        pageContent.addEventListener('touchstart', (e) => {
            startX = e.touches[0].clientX;
            startY = e.touches[0].clientY;
        }, { passive: true });
        
        pageContent.addEventListener('touchend', (e) => {
            endX = e.changedTouches[0].clientX;
            endY = e.changedTouches[0].clientY;
            
            const deltaX = endX - startX;
            const deltaY = endY - startY;
            const threshold = 50;
            
            // Horizontal swipe detection
            if (Math.abs(deltaX) > Math.abs(deltaY) && Math.abs(deltaX) > threshold) {
                if (deltaX > 0) {
                    this.previousPage(); // Swipe right = previous page
                } else {
                    this.nextPage(); // Swipe left = next page
                }
            }
        }, { passive: true });
    }
    
    loadInitialData() {
        // Load theme preference
        const savedTheme = localStorage.getItem('pdfTutorial_theme') || 'light';
        this.setTheme(savedTheme);
    }
    
    async loadPage(pageNum) {
        if (pageNum < 1 || pageNum > this.totalPages) return;
        
        const pageContent = document.getElementById('pageContent');
        if (!pageContent) return;
        
        // Show loading
        pageContent.innerHTML = `
            <div class="loading-spinner text-center py-5">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading page ${pageNum}...</span>
                </div>
            </div>
        `;
        
        try {
            const response = await fetch(`/api/page/${pageNum}`);
            const data = await response.json();
            
            if (data.success) {
                this.currentPage = pageNum;
                this.renderPage(data.page);
                this.updateNavigation();
                this.updateProgress();
                this.updateThumbnails();
                
                // Update page indicator
                document.getElementById('currentPage').textContent = pageNum;
            } else {
                this.showError(data.error || 'Failed to load page');
            }
        } catch (error) {
            console.error('Error loading page:', error);
            this.showError('Network error occurred while loading page');
        }
    }
    
    renderPage(pageData) {
        const pageContent = document.getElementById('pageContent');
        if (!pageContent) return;
        
        let html = `
            <div class="page-card animate-in">
                <div class="page-header">
                    <div class="page-number">
                        Page ${pageData.page_number}
                    </div>
                    <div class="page-actions">
                        <button class="btn btn-sm btn-outline-primary bookmark-btn ${this.bookmarks.includes(pageData.page_number) ? 'bookmarked' : ''}" 
                                onclick="app.toggleBookmark()" title="Bookmark this page">
                            <i class="fas fa-bookmark"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-secondary" 
                                onclick="app.addNote()" title="Add note">
                            <i class="fas fa-sticky-note"></i>
                        </button>
                    </div>
                </div>
        `;
        
        // Add structured content in order
        if (pageData.elements && pageData.elements.length > 0) {
            // Render elements in their original order for proper layout
            pageData.elements.forEach(element => {
                if (element.type === 'text') {
                    const textContent = element.content;
                    const fontSize = textContent.fontsize ? Math.max(12, Math.min(textContent.fontsize, 24)) : 14;
                    html += `
                        <div class="page-text-block" style="font-size: ${fontSize}px; margin-bottom: 0.5rem;">
                            ${this.escapeHtml(textContent.text)}
                        </div>
                    `;
                } else if (element.type === 'image') {
                    const imageContent = element.content;
                    html += `
                        <div class="page-image mb-3">
                            <img src="/${imageContent.path}" class="pdf-image img-fluid" alt="Page ${pageData.page_number} Image" 
                                 style="max-width: 100%; height: auto;">
                        </div>
                    `;
                } else if (element.type === 'table') {
                    const tableContent = element.content;
                    if (tableContent.data && tableContent.data.length > 0) {
                        html += '<div class="page-table mb-3">';
                        html += '<table class="table table-striped pdf-table">';
                        tableContent.data.forEach((row, rowIndex) => {
                            if (row) {
                                const tag = rowIndex === 0 ? 'th' : 'td';
                                html += '<tr>';
                                row.forEach(cell => {
                                    html += `<${tag}>${this.escapeHtml(cell || '')}</${tag}>`;
                                });
                                html += '</tr>';
                            }
                        });
                        html += '</table></div>';
                    }
                }
            });
        } else {
            // Fallback to old format if elements not available
            if (pageData.text) {
                html += `
                    <div class="page-text">
                        ${this.escapeHtml(pageData.text)}
                    </div>
                `;
            }
        }
        
        // Legacy table rendering for fallback
        if (!pageData.elements && pageData.tables && pageData.tables.length > 0) {
            html += '<div class="page-tables">';
            pageData.tables.forEach((table, index) => {
                let tableData = table.data || table; // Handle both new and old format
                if (tableData && tableData.length > 0) {
                    html += '<table class="table table-striped pdf-table mb-3">';
                    tableData.forEach((row, rowIndex) => {
                        if (row) {
                            const tag = rowIndex === 0 ? 'th' : 'td';
                            html += '<tr>';
                            row.forEach(cell => {
                                html += `<${tag}>${this.escapeHtml(cell || '')}</${tag}>`;
                            });
                            html += '</tr>';
                        }
                    });
                    html += '</table>';
                }
            });
            html += '</div>';
        }
        
        // Legacy image rendering for fallback
        if (!pageData.elements && pageData.images && pageData.images.length > 0) {
            html += '<div class="page-images">';
            pageData.images.forEach(image => {
                html += `
                    <div class="mb-3">
                        <img src="/${image.path}" class="pdf-image img-fluid" alt="Page ${pageData.page_number} Image">
                    </div>
                `;
            });
            html += '</div>';
        }
        
        // Add note if exists
        const noteText = this.notes[pageData.page_number];
        if (noteText) {
            html += `
                <div class="page-note alert alert-info">
                    <h6><i class="fas fa-sticky-note me-2"></i>Your Note:</h6>
                    <p class="mb-0">${this.escapeHtml(noteText)}</p>
                </div>
            `;
        }
        
        html += '</div>';
        
        // Apply page transition
        pageContent.style.opacity = '0';
        setTimeout(() => {
            pageContent.innerHTML = html;
            pageContent.style.opacity = '1';
        }, 150);
    }
    
    updateNavigation() {
        const prevBtn = document.getElementById('prevBtn');
        const nextBtn = document.getElementById('nextBtn');
        
        if (prevBtn) {
            prevBtn.disabled = this.currentPage <= 1;
        }
        
        if (nextBtn) {
            nextBtn.disabled = this.currentPage >= this.totalPages;
        }
        
        // Update jump to page input
        const jumpInput = document.getElementById('jumpToPage');
        if (jumpInput) {
            jumpInput.value = this.currentPage;
        }
    }
    
    updateProgress() {
        const progressBar = document.getElementById('readingProgress');
        if (progressBar && this.totalPages > 0) {
            const progress = (this.currentPage / this.totalPages) * 100;
            progressBar.style.width = `${progress}%`;
        }
    }
    
    updateThumbnails() {
        document.querySelectorAll('.thumbnail-item').forEach(thumb => {
            const page = parseInt(thumb.dataset.page);
            thumb.classList.toggle('active', page === this.currentPage);
        });
        
        // Scroll active thumbnail into view
        const activeThumb = document.querySelector('.thumbnail-item.active');
        if (activeThumb) {
            activeThumb.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    }
    
    // Navigation methods
    previousPage() {
        if (this.currentPage > 1) {
            this.goToPage(this.currentPage - 1);
        }
    }
    
    nextPage() {
        if (this.currentPage < this.totalPages) {
            this.goToPage(this.currentPage + 1);
        }
    }
    
    jumpToPage() {
        const jumpInput = document.getElementById('jumpToPage');
        const pageNum = parseInt(jumpInput.value);
        
        if (pageNum >= 1 && pageNum <= this.totalPages) {
            this.goToPage(pageNum);
        } else {
            jumpInput.value = this.currentPage;
        }
    }
    
    goToPage(pageNum) {
        if (pageNum >= 1 && pageNum <= this.totalPages && pageNum !== this.currentPage) {
            this.loadPage(pageNum);
        }
    }
    
    // Search functionality
    async performSearch() {
        const searchInput = document.getElementById('searchInput');
        const query = searchInput.value.trim();
        const resultsContainer = document.getElementById('searchResults');
        
        if (!query || !resultsContainer) return;
        
        if (query.length < 2) {
            resultsContainer.innerHTML = '<p class="text-muted text-center">Enter at least 2 characters</p>';
            return;
        }
        
        resultsContainer.innerHTML = '<div class="text-center"><div class="spinner-border spinner-border-sm"></div></div>';
        
        try {
            const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
            const data = await response.json();
            
            if (data.results.length === 0) {
                resultsContainer.innerHTML = '<p class="text-muted text-center">No results found</p>';
                return;
            }
            
            let html = '';
            data.results.forEach(result => {
                result.matches.forEach(match => {
                    html += `
                        <div class="search-result" onclick="app.goToPage(${result.page_number})">
                            <div class="search-result-page">Page ${result.page_number}</div>
                            <div class="search-result-context">
                                ${this.highlightText(match.context, query)}
                            </div>
                        </div>
                    `;
                });
            });
            
            resultsContainer.innerHTML = html;
        } catch (error) {
            console.error('Search error:', error);
            resultsContainer.innerHTML = '<p class="text-danger text-center">Search failed</p>';
        }
    }
    
    highlightText(text, query) {
        const regex = new RegExp(`(${this.escapeRegex(query)})`, 'gi');
        return this.escapeHtml(text).replace(regex, '<span class="highlight">$1</span>');
    }
    
    // Bookmark functionality
    async toggleBookmark() {
        const isBookmarked = this.bookmarks.includes(this.currentPage);
        const action = isBookmarked ? 'remove' : 'add';
        
        try {
            const response = await fetch('/api/bookmark', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    page_number: this.currentPage,
                    action: action
                })
            });
            
            const data = await response.json();
            if (data.success) {
                this.bookmarks = data.bookmarks;
                this.updateBookmarkUI();
                this.refreshBookmarksList();
            }
        } catch (error) {
            console.error('Bookmark error:', error);
        }
    }
    
    async loadBookmarks() {
        try {
            const response = await fetch('/api/bookmark');
            const data = await response.json();
            this.bookmarks = data.bookmarks || [];
            this.updateBookmarkUI();
            this.refreshBookmarksList();
        } catch (error) {
            console.error('Error loading bookmarks:', error);
        }
    }
    
    updateBookmarkUI() {
        const bookmarkBtn = document.querySelector('.bookmark-btn');
        const fabBookmark = document.getElementById('toggleBookmark');
        
        const isBookmarked = this.bookmarks.includes(this.currentPage);
        
        if (bookmarkBtn) {
            bookmarkBtn.classList.toggle('bookmarked', isBookmarked);
        }
        
        if (fabBookmark) {
            fabBookmark.classList.toggle('bookmarked', isBookmarked);
        }
    }
    
    refreshBookmarksList() {
        const bookmarksList = document.getElementById('bookmarksList');
        if (!bookmarksList) return;
        
        if (this.bookmarks.length === 0) {
            bookmarksList.innerHTML = '<p class="text-muted text-center">No bookmarks yet</p>';
            return;
        }
        
        let html = '';
        this.bookmarks.sort((a, b) => a - b).forEach(pageNum => {
            html += `
                <div class="bookmark-item" onclick="app.goToPage(${pageNum})">
                    <div class="bookmark-page">Page ${pageNum}</div>
                </div>
            `;
        });
        
        bookmarksList.innerHTML = html;
    }
    
    // Notes functionality
    addNote() {
        const modal = new bootstrap.Modal(document.getElementById('noteModal'));
        const noteText = document.getElementById('noteText');
        
        // Pre-fill with existing note if any
        noteText.value = this.notes[this.currentPage] || '';
        modal.show();
    }
    
    async saveNote() {
        const noteText = document.getElementById('noteText').value.trim();
        
        try {
            const response = await fetch('/api/notes', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    page_number: this.currentPage,
                    note: noteText
                })
            });
            
            const data = await response.json();
            if (data.success) {
                if (noteText) {
                    this.notes[this.currentPage] = noteText;
                } else {
                    delete this.notes[this.currentPage];
                }
                
                // Close modal and refresh page to show note
                const modal = bootstrap.Modal.getInstance(document.getElementById('noteModal'));
                modal.hide();
                
                this.loadPage(this.currentPage);
                this.refreshNotesList();
            }
        } catch (error) {
            console.error('Note save error:', error);
        }
    }
    
    async loadNotes() {
        try {
            const response = await fetch('/api/notes');
            const data = await response.json();
            this.notes = data.notes || {};
            this.refreshNotesList();
        } catch (error) {
            console.error('Error loading notes:', error);
        }
    }
    
    refreshNotesList() {
        const notesList = document.getElementById('notesList');
        if (!notesList) return;
        
        const notePages = Object.keys(this.notes);
        if (notePages.length === 0) {
            notesList.innerHTML = '<p class="text-muted text-center">No notes yet</p>';
            return;
        }
        
        let html = '';
        notePages.sort((a, b) => parseInt(a) - parseInt(b)).forEach(pageNum => {
            html += `
                <div class="note-item" onclick="app.goToPage(${pageNum})">
                    <div class="note-page">Page ${pageNum}</div>
                    <div class="note-text">${this.escapeHtml(this.notes[pageNum])}</div>
                </div>
            `;
        });
        
        notesList.innerHTML = html;
    }
    
    // Theme functionality
    toggleTheme() {
        const currentTheme = document.body.dataset.theme === 'dark' ? 'light' : 'dark';
        this.setTheme(currentTheme);
    }
    
    setTheme(theme) {
        document.body.dataset.theme = theme;
        localStorage.setItem('pdfTutorial_theme', theme);
        
        const themeIcon = document.querySelector('#themeToggle i');
        if (themeIcon) {
            themeIcon.className = theme === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
        }
    }
    
    // UI helpers
    toggleSidebar() {
        const sidebar = document.getElementById('sidebar');
        if (sidebar) {
            this.sidebarVisible = !this.sidebarVisible;
            sidebar.classList.toggle('show', this.sidebarVisible);
        }
    }
    
    toggleFabMenu() {
        const fabMenu = document.querySelector('.fab-menu');
        this.fabMenuOpen = !this.fabMenuOpen;
        fabMenu.classList.toggle('active', this.fabMenuOpen);
    }
    
    closeFabMenu() {
        const fabMenu = document.querySelector('.fab-menu');
        this.fabMenuOpen = false;
        fabMenu.classList.remove('active');
    }
    
    checkMobileLayout() {
        const isMobile = window.innerWidth <= 991.98;
        if (!isMobile && this.sidebarVisible) {
            this.toggleSidebar(); // Close sidebar on desktop
        }
    }
    
    // Keyboard navigation
    handleKeyboardNavigation(e) {
        // Don't interfere with form inputs
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
            return;
        }
        
        switch (e.key) {
            case 'ArrowLeft':
            case 'PageUp':
                e.preventDefault();
                this.previousPage();
                break;
            case 'ArrowRight':
            case 'PageDown':
            case ' ':
                e.preventDefault();
                this.nextPage();
                break;
            case 'Home':
                e.preventDefault();
                this.goToPage(1);
                break;
            case 'End':
                e.preventDefault();
                this.goToPage(this.totalPages);
                break;
            case 'b':
                if (e.ctrlKey || e.metaKey) {
                    e.preventDefault();
                    this.toggleBookmark();
                }
                break;
            case 'f':
                if (e.ctrlKey || e.metaKey) {
                    e.preventDefault();
                    document.getElementById('searchInput')?.focus();
                }
                break;
        }
    }
    
    // Utility methods
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    escapeRegex(string) {
        return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }
    
    showError(message) {
        const pageContent = document.getElementById('pageContent');
        if (pageContent) {
            pageContent.innerHTML = `
                <div class="alert alert-danger text-center">
                    <i class="fas fa-exclamation-triangle me-2"></i>
                    ${this.escapeHtml(message)}
                </div>
            `;
        }
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new PDFTutorialApp();
});

// Service Worker registration for PWA (basic implementation)
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/static/sw.js')
            .then(registration => {
                console.log('SW registered: ', registration);
            })
            .catch(registrationError => {
                console.log('SW registration failed: ', registrationError);
            });
    });
}
