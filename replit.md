# PDF Tutorial App

## Overview

The PDF Tutorial App is a mobile-first Progressive Web Application (PWA) built with Flask that transforms static PDFs into interactive, tutorial-style experiences. The app extracts content from uploaded PDFs and presents it in a modern, responsive interface with features like bookmarks, notes, search functionality, and theme switching. It's designed to make PDF consumption more engaging and accessible on mobile devices.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Frontend Architecture
- **Single Page Application**: Uses vanilla JavaScript with a class-based architecture (`PDFTutorialApp`) for client-side state management
- **Mobile-First Responsive Design**: Bootstrap 5 framework with custom CSS variables for theme support
- **Progressive Web App**: Service worker implementation for offline functionality and caching
- **Template Engine**: Jinja2 templates with a base template inheritance pattern

### Backend Architecture
- **Flask Web Framework**: Lightweight Python web server with simple route-based architecture
- **File Upload System**: Handles PDF uploads with security validation and file size limits
- **Content Extraction**: Uses pdfplumber library for extracting text, images, and tables from PDF files
- **Session Management**: Flask sessions for maintaining user state across requests

### Data Storage Solutions
- **File System Storage**: Uploaded PDFs and extracted content stored in local directories (`static/uploads`, `static/extracted`)
- **Client-Side Storage**: localStorage for persisting user preferences, bookmarks, and notes
- **Memory-Based Processing**: PDF content processed in-memory during extraction

### User Interface Components
- **Theme System**: CSS custom properties enabling light/dark mode switching
- **Navigation Controls**: Page-based navigation with smooth transitions and gesture support
- **Interactive Elements**: Floating Action Button (FAB) menu, search functionality, and bookmark system
- **Content Display**: Dynamic HTML rendering of extracted PDF content with mobile-optimized layout

### External Dependencies
- **PDF Processing**: pdfplumber for text and table extraction, PIL (Python Imaging Library) for image handling
- **Frontend Libraries**: Bootstrap 5 for UI components, Font Awesome for icons
- **Web Standards**: Service Worker API for PWA functionality, localStorage for client-side persistence
- **Development Tools**: Werkzeug for WSGI middleware and security utilities