"""
APexpython.py - Simple Python Web Service for Oracle APEX Standalone Application
This module provides a Flask-based REST API that can be exposed to Oracle APEX.
"""

from flask import Flask, jsonify, request
import json
from datetime import datetime

# Initialize Flask application
app = Flask(__name__)

# Basic health check endpoint
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    return jsonify({
        'status': 'success',
        'message': 'Service is running',
        'timestamp': datetime.now().isoformat()
    }), 200


# Main hello world endpoint
@app.route('/hello', methods=['GET', 'POST'])
def hello_world():
    """
    Main endpoint that returns hello world message
    Can be called from Oracle APEX
    """
    name = request.args.get('name', 'World')
    
    response = {
        'status': 'success',
        'message': f'Hello {name}!',
        'timestamp': datetime.now().isoformat(),
        'service': 'APexpython'
    }
    
    return jsonify(response), 200


# Endpoint to display simple HTML page
@app.route('/', methods=['GET'])
def index():
    """Simple HTML page"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>APexpython - Oracle APEX Service</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            }
            .container {
                background: white;
                padding: 40px;
                border-radius: 10px;
                box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
                text-align: center;
            }
            h1 {
                color: #333;
                margin: 0;
            }
            p {
                color: #666;
                font-size: 16px;
            }
            .endpoint {
                background: #f5f5f5;
                padding: 10px;
                margin: 10px 0;
                border-radius: 5px;
                font-family: monospace;
                color: #667eea;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Hello World!</h1>
            <p>APexpython Service for Oracle APEX Standalone Application</p>
            <p>Service is running successfully</p>
            <div style="margin-top: 30px;">
                <h3>Available Endpoints:</h3>
                <div class="endpoint">GET /hello?name=YourName</div>
                <div class="endpoint">GET /health</div>
                <p style="font-size: 14px; color: #999; margin-top: 20px;">
                    Use these endpoints in your Oracle APEX application
                </p>
            </div>
        </div>
    </body>
    </html>
    """
    return html_content, 200, {'Content-Type': 'text/html'}


# Echo endpoint - useful for testing integration with APEX
@app.route('/echo', methods=['POST'])
def echo():
    """
    Echo endpoint for testing
    Returns the received data back as JSON
    """
    try:
        data = request.get_json()
        response = {
            'status': 'success',
            'echo': data,
            'timestamp': datetime.now().isoformat()
        }
        return jsonify(response), 200
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 400


# Error handler
@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({
        'status': 'error',
        'message': 'Endpoint not found',
        'path': request.path
    }), 404


# Main entry point
if __name__ == '__main__':
    print("=" * 60)
    print("APexpython - Oracle APEX Standalone Service")
    print("=" * 60)
    print("\nStarting Flask application...")
    print("\nAvailable Endpoints:")
    print("  - GET  http://localhost:5000/          (Main page)")
    print("  - GET  http://localhost:5000/hello     (Hello message)")
    print("  - GET  http://localhost:5000/health    (Health check)")
    print("  - POST http://localhost:5000/echo      (Echo service)")
    print("\nTo use with Oracle APEX:")
    print("  1. Call REST API endpoint from APEX")
    print("  2. Example: http://<your-server>:5000/hello?name=APEX")
    print("\nPress CTRL+C to stop the server")
    print("=" * 60)
    print("\n")
    
    # Run the Flask application
    app.run(host='0.0.0.0', port=5000, debug=True)
