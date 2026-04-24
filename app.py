from flask import Flask, request, jsonify, send_file
import json
import subprocess
import os
import tempfile

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.route('/')
def index():
    with open(os.path.join(BASE_DIR, 'index.html'), 'r') as f:
        html_content = f.read()
    return html_content


@app.route('/logo.png')
def logo():
    return send_file(os.path.join(BASE_DIR, 'logo.png'), mimetype='image/png')

@app.route('/api/scrape', methods=['POST'])
def scrape():
    try:
        data = request.json or {}
        url = data.get('url', '').strip()
        backend = str(data.get('backend', 'auto')).strip().lower()
        
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
                'python3', scraper_path, url,
                '--output', output_file,
                '--max-pages', '12'
            ]
            if selected_backend:
                cmd.extend(['--backend', selected_backend])

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)

            payload = None
            if os.path.exists(output_file):
                try:
                    with open(output_file, 'r') as f:
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
