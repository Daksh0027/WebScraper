from flask import Flask, request, jsonify, send_file
import json
import subprocess
import os
import tempfile
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.route('/')
def index():
    with open(os.path.join(BASE_DIR, 'index.html'), 'r', encoding='utf-8') as f:
        html_content = f.read()
    return html_content


@app.route('/logo.png')
def logo():
    return send_file(os.path.join(BASE_DIR, 'logo.png'), mimetype='image/png')

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json or {}
    message = data.get('message', '').strip()
    if not message:
        return jsonify({'error': 'Message required'}), 400

    api_key = os.environ.get('GOOG_API_KEY') or os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return jsonify({'error': 'Please set the GEMINI_API_KEY environment variable to use the AI Chatbot.'}), 400

    if not GENAI_AVAILABLE:
         return jsonify({'error': 'The google-genai module is missing. Please run `pip install google-genai`.'}), 400

    try:
        client = genai.Client(api_key=api_key)
        
        context_data = data.get('context')
        context_str = ""
        if context_data:
            # Provide the scraped data as contextual background
            context_str = f"Context about the scraped website ({context_data.get('domain')}):\n"
            context_str += json.dumps(context_data, ensure_ascii=False)[:30000] # Pass a summarized cut
            context_str += "\n\nAnswer the user based on the context above. If the context does not contain the answer, answer generally."

        # Simple context prompt
        prompt = (
            "You are WICK AI, an expert website intelligence assistant. "
            "You provide accurate, brief, and helpful answers.\n\n"
            f"{context_str}\n\n"
            f"User: {message}"
        )
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return jsonify({'reply': response.text})
    except Exception as e:
        return jsonify({'error': f'AI Error: {str(e)}'}), 500

@app.route('/api/scrape', methods=['POST'])
def scrape():
    try:
        data = request.json or {}
        url = data.get('url', '').strip()
        backend = str(data.get('backend', 'auto')).strip().lower()
        max_pages = str(data.get('max_pages', 25)).strip()
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400

        if backend not in {'auto', 'urllib', 'playwright'}:
            return jsonify({'error': 'backend must be one of: auto, urllib, playwright'}), 400
        
        # Ensure URL has a scheme
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        scraper_path = os.path.join(BASE_DIR, 'scraper.py')

        def run_scraper(selected_backend: str | None):
            with tempfile.NamedTemporaryFile(prefix='scrape_result_', suffix='.json', delete=False) as tmp:
                output_file = tmp.name

            cmd = [
                sys.executable, scraper_path, url,
                '--output', output_file,
                '--max-pages', max_pages
            ]
            if selected_backend:
                cmd.extend(['--backend', selected_backend])

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)

            payload = None
            if os.path.exists(output_file):
                try:
                    with open(output_file, 'r', encoding='utf-8') as f:
                        text = f.read().strip()
                    if text:
                        payload = json.loads(text)
                except json.JSONDecodeError:
                    payload = None
                finally:
                    os.remove(output_file)

            return result, payload

        def page_count(payload):
            if not payload:
                return 0
            analysis = payload.get('analysis') or {}
            if isinstance(analysis.get('page_count'), int):
                return analysis['page_count']
            pages = payload.get('pages')
            if isinstance(pages, list):
                return len(pages)
            return 0

        first_backend = None if backend == 'auto' else backend
        result, payload = run_scraper(first_backend if first_backend else 'urllib')

        if result.returncode != 0:
            return jsonify({'error': f'Scraper error: {result.stderr.strip() or result.stdout.strip() or "Unknown error"}'}), 500

        if payload and page_count(payload) > 0:
            payload['crawl_backend'] = first_backend if first_backend else 'urllib'
            return jsonify(payload)

        if backend == 'playwright':
            return jsonify({
                'error': 'No crawlable pages were found with Playwright. The site may block automated browsing.',
            }), 502

        pw_result, pw_payload = run_scraper('playwright')
        if pw_result.returncode == 0 and pw_payload and page_count(pw_payload) > 0:
            pw_payload['crawl_backend'] = 'playwright'
            return jsonify(pw_payload)

        play_err = (pw_result.stderr or pw_result.stdout or '').strip()
        if 'No module named playwright' in play_err:
            return jsonify({
                'error': 'No crawlable pages were found using urllib, and Playwright fallback is not installed. Install with: pip install playwright && playwright install chromium',
            }), 502

        return jsonify({
            'error': 'No crawlable pages were found. The site may be blocking bot traffic or requiring interactive browsing.',
        }), 502
        
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Scraping timed out'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='localhost', port=5000)
