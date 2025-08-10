from flask import Flask, request, jsonify, render_template, send_file, make_response
from flask_cors import CORS
import base64
from PIL import Image, ImageEnhance, ImageFilter
import pytesseract
import io
import json
import random
import csv
from io import StringIO, BytesIO
from openpyxl import Workbook
import google.generativeai as genai
import requests
import easyocr
import numpy as np

# 🔐 Ganti dengan API Key Gemini
GEMINI_API_KEY = "AIzaSyAyr6hBJPs0oi9EqYZakphFIel-3X1d3fQ"
genai.configure(api_key=GEMINI_API_KEY)

app = Flask(__name__)
CORS(app)

@app.route('/')
def index():
    return render_template("index.html")

# ✨ Fungsi estimasi harga pakai Gemini
def get_price_estimate_gemini(nama_produk, daerah="Jakarta"):
    prompt = f"""
    Kamu adalah sistem yang memberikan estimasi harga produk di pasaran Indonesia berdasarkan daerah.

    Produk: {nama_produk}
    Daerah: {daerah}
    Tampilkan jawaban dalam format JSON:
    {{
      "hargaBeli": <harga_beli>,
      "hargaJual": <harga_jual>
    }}
    Harga jual harus lebih tinggi dari harga beli (margin 10-30%).
    """
    try:
        model = genai.GenerativeModel("gemini-2.5-pro")
        response = model.generate_content(prompt)
        text = response.text.strip()
        # Coba cari JSON di dalam text
        try:
            data = json.loads(text)
        except Exception:
            # Coba ekstrak JSON dari text jika ada teks lain
            import re
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
            else:
                raise ValueError("No JSON found in Gemini response")
        # Validasi harga jual > harga beli
        if data["hargaJual"] <= data["hargaBeli"]:
            data["hargaJual"] = int(data["hargaBeli"] * 1.15)
        return data
    except Exception as e:
        print("Gagal ambil harga dari Gemini:", e)
        # Fallback: harga beli acak, harga jual = beli + margin 15-25%
        harga_beli = random.randint(8000, 20000)
        margin = random.uniform(0.15, 0.25)
        harga_jual = int(harga_beli * (1 + margin))
        return {
            "hargaBeli": harga_beli,
            "hargaJual": harga_jual
        }

def preprocess_image(image):
    # Konversi ke grayscale
    image = image.convert('L')
    # Perbesar jika terlalu kecil
    if image.width < 400:
        ratio = 400 / image.width
        image = image.resize((int(image.width * ratio), int(image.height * ratio)), Image.LANCZOS)
    # Tingkatkan kontras
    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(3)
    # Hilangkan noise
    image = image.filter(ImageFilter.MedianFilter(size=3))
    # Thresholding ringan
    image = image.point(lambda x: 0 if x < 120 else 255, '1')
    return image

def extract_best_line(text):
    # Ambil baris terpanjang yang bukan angka saja
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if not lines:
        return "Produk A"
    lines = [l for l in lines if not l.isdigit()]
    if not lines:
        return "Produk A"
    return max(lines, key=len)

def ocr_with_vision_api(image_base64, api_key):
    url = f"https://vision.googleapis.com/v1/images:annotate?key={api_key}"
    headers = {"Content-Type": "application/json"}
    body = {
        "requests": [{
            "image": {"content": image_base64},
            "features": [{"type": "TEXT_DETECTION"}]
        }]
    }
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        annotations = result.get("responses", [{}])[0].get("textAnnotations", [])
        if annotations:
            # Ambil baris terpanjang dari hasil Vision
            lines = [l.strip() for l in annotations[0]["description"].split('\n') if l.strip()]
            lines = [l for l in lines if not l.isdigit()]
            if lines:
                return max(lines, key=len)
        return None
    except Exception as e:
        print("Vision OCR error:", e)
        return None

reader = easyocr.Reader(['id', 'en'], gpu=False)  # Inisialisasi sekali saja

def ocr_with_easyocr(image):
    try:
        result = reader.readtext(np.array(image), detail=0, paragraph=True)
        # Ambil baris terpanjang yang bukan angka saja
        lines = [l.strip() for l in result if l.strip()]
        lines = [l for l in lines if not l.isdigit()]
        if lines:
            return max(lines, key=len)
        return None
    except Exception as e:
        print("EasyOCR error:", e)
        return None

def ocr_with_tesseract(image):
    # Gunakan mode block, tanpa whitelist karakter
    custom_config = r'--psm 6'
    text = pytesseract.image_to_string(image, config=custom_config)
    return text

VISION_API_KEY = "AIzaSyDLlsqWVQohaYgaCDFenN7jQW_IZDiGu0o"  # Ganti dengan API Key Vision Anda

@app.route('/ocr', methods=['POST'])
def ocr():
    data = request.get_json()
    image_base64 = data['image'].split(',')[1]
    image = Image.open(io.BytesIO(base64.b64decode(image_base64)))

    # 1. Coba n8n dulu
    nama_produk = ocr_with_n8n(image_base64)
    # 2. Jika gagal, fallback ke EasyOCR
    if not nama_produk:
        nama_produk = ocr_with_easyocr(image)
    # 3. Jika masih gagal, fallback ke Tesseract
    if not nama_produk:
        image = preprocess_image(image)
        text = ocr_with_tesseract(image)
        nama_produk = extract_best_line(text)

    # 🔄 Pakai Gemini
    harga_data = get_price_estimate_gemini(nama_produk)

    # 🔄 Barcode otomatis
    barcode = get_barcode_for_product(nama_produk)

    return jsonify({
        "nama": nama_produk,
        "hargaBeli": harga_data["hargaBeli"],
        "hargaJual": harga_data["hargaJual"],
        "barcode": barcode
    })

@app.route('/save', methods=['POST'])
def save():
    data = request.get_json()
    try:
        with open("produk.json", "r") as f:
            produk_list = json.load(f)
    except:
        produk_list = []

    produk_list.append(data)
    with open("produk.json", "w") as f:
        json.dump(produk_list, f, indent=4)

    return jsonify({"status": "success"})

@app.route('/produk', methods=['GET'])
def get_produk():
    try:
        with open("produk.json", "r") as f:
            produk_list = json.load(f)
    except:
        produk_list = []

    return jsonify(produk_list)

@app.route('/update/<int:index>', methods=['PUT'])
def update_produk(index):
    data = request.get_json()
    try:
        with open("produk.json", "r") as f:
            produk_list = json.load(f)
    except:
        return jsonify({"error": "Data produk tidak ditemukan"}), 404

    if 0 <= index < len(produk_list):
        produk_list[index] = data
        with open("produk.json", "w") as f:
            json.dump(produk_list, f, indent=4)
        return jsonify({"status": "updated"})
    else:
        return jsonify({"error": "Index tidak valid"}), 400

@app.route('/delete/<int:index>', methods=['DELETE'])
def delete_produk(index):
    try:
        with open("produk.json", "r") as f:
            produk_list = json.load(f)
    except:
        return jsonify({"error": "Data produk tidak ditemukan"}), 404

    if 0 <= index < len(produk_list):
        deleted = produk_list.pop(index)
        with open("produk.json", "w") as f:
            json.dump(produk_list, f, indent=4)
        return jsonify({"status": "deleted", "deleted": deleted})
    else:
        return jsonify({"error": "Index tidak valid"}), 400

@app.route('/export/json')
def export_json():
    return send_file("produk.json", as_attachment=True)

@app.route('/export/csv')
def export_csv():
    try:
        with open("produk.json", "r") as f:
            data = json.load(f)
    except:
        data = []

    headers = [
        "Internal ID Variant (Do Not Edit)", "Category", "SKU", "Items Name (Do Not Edit)",
        "ecommerce item? (Yes/No)", "Pre-order ? (Yes/No)", "Processing days", "Weight (gm)",
        "Length (cm)", "Width (cm)", "Height (cm)", "Condition", "Brand Name", "Variant name",
        "Basic - Price", "Image 1 (for Online Store)", "Image 2 (for Online Store)", "Image 3 (for Online Store)",
        "Image 4 (for Online Store)", "Image 5 (for Online Store)", "Image 6 (for Online Store)",
        "Image 7 (for Online Store)", "Image 8 (for Online Store)", "Image 9 (for Online Store)",
        "Image 10 (for Online Store)", "Image 11 (for Online Store)", "Image 12 (for Online Store)",
        "In Stock", "Track Stock", "Track Alert", "Stock Alert", "Track Cost", "Cost Amount"
    ]

    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(headers)

    for idx, p in enumerate(data):
        # --- Ambil data dari form MokaPos jika ada, fallback ke default ---
        kategori = p.get("kategori", "General")
        sku = p.get("barcode", f"SKU{idx+1:06d}")
        nama = p.get("nama", f"Produk {idx+1}")
        variant_name = p.get("variant", "").strip() or nama or "Default"
        brand = p.get("brand", "BrandA")
        harga_jual = p.get("hargaJual", 10000)
        harga_beli = p.get("hargaBeli", 8000)
        stok = p.get("stok", 10)
        try:
            stok = int(stok)
        except:
            stok = 10

        row = [
            idx + 1,              # Internal ID Variant (Do Not Edit)
            kategori,             # Category
            sku,                  # SKU
            nama,                 # Items Name (Do Not Edit)
            "Yes",                # ecommerce item? (Yes/No)
            "No",                 # Pre-order ? (Yes/No)
            1,                    # Processing days
            100,                  # Weight (gm)
            10,                   # Length (cm)
            10,                   # Width (cm)
            10,                   # Height (cm)
            "New",                # Condition
            brand,                # Brand Name
            variant_name,         # Variant name
            harga_jual,           # Basic - Price
            "", "", "", "", "", "", "", "", "", "", "", "",  # Image 1-12
            stok,                 # In Stock (wajib angka)
            "Yes",                # Track Stock
            "No",                 # Track Alert
            5,                    # Stock Alert
            "No",                 # Track Cost
            harga_beli            # Cost Amount
        ]
        writer.writerow(row)

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=produk_mokapos.csv"
    output.headers["Content-type"] = "text/csv"
    return output

@app.route('/export/excel')
def export_excel():
    try:
        with open("produk.json", "r") as f:
            data = json.load(f)
    except:
        data = []

    wb = Workbook()
    ws = wb.active
    ws.title = "Daftar Produk"
    ws.append(["Nama", "Harga Beli", "Harga Jual", "Barcode"])

    for p in data:
        ws.append([p["nama"], p["hargaBeli"], p["hargaJual"], p["barcode"]])

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(output, download_name="produk.xlsx", as_attachment=True)

@app.route('/api/produk')
def api_produk():
    try:
        with open("produk.json", "r") as f:
            data = json.load(f)
    except:
        data = []
    return jsonify(data)

@app.route('/chat', methods=['POST'])
def chatbot():
    data = request.get_json()
    question = data.get("question", "")

    prompt = f"""
    Kamu adalah asisten yang membantu pengguna aplikasi OCR Produk Scanner.
    Jawablah pertanyaan berikut secara singkat dan jelas:
    {question}
    """
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        answer = response.text.strip()
    except Exception as e:
        print("Chatbot error:", e)
        answer = "Maaf, saya tidak bisa menjawab sekarang."

    return jsonify({"answer": answer})

@app.route('/chat-image', methods=['POST'])
def chat_image():
    data = request.get_json()
    image_base64 = data.get('image').split(',')[1]
    daerah = data.get('daerah', 'Jakarta')
    image = Image.open(io.BytesIO(base64.b64decode(image_base64)))

    # 1. Coba n8n dulu
    nama_produk = ocr_with_n8n(image_base64)
    # 2. Jika gagal, fallback ke EasyOCR
    if not nama_produk:
        nama_produk = ocr_with_easyocr(image)
    # 3. Jika masih gagal, fallback ke Tesseract
    if not nama_produk:
        image = preprocess_image(image)
        text = ocr_with_tesseract(image)
        nama_produk = extract_best_line(text)

    # 🔄 Pakai Gemini
    harga_data = get_price_estimate_gemini(nama_produk, daerah)

    # 🔄 Barcode otomatis
    barcode = get_barcode_for_product(nama_produk)
    harga_data["nama"] = nama_produk
    harga_data["barcode"] = barcode
    return jsonify(harga_data)

def get_barcode_for_product(nama_produk):
    # Cek ke Open Food Facts
    try:
        url = f"https://world.openfoodfacts.org/cgi/search.pl?search_terms={nama_produk}&search_simple=1&action=process&json=1&page_size=1"
        resp = requests.get(url, timeout=5)
        data = resp.json()
        if data.get("products"):
            product = data["products"][0]
            barcode = product.get("code")
            if barcode and barcode.isdigit():
                return barcode
    except Exception as e:
        print("Barcode OFF error:", e)
    # Jika tidak ditemukan, pakai template
    return "BR" + str(random.randint(100000, 999999))

def ocr_with_n8n(image_base64):
    """Kirim gambar ke n8n dalam format file asli (JPG/PNG), bukan base64"""
    try:
        url = "https://mastah.app.n8n.cloud/webhook-test/waan"
        
        # Decode base64 ke bytes
        image_bytes = base64.b64decode(image_base64)
        
        # Kirim sebagai multipart/form-data dengan file binary
        files = {
            'image': ('image.jpg', BytesIO(image_bytes), 'image/jpeg')
        }
        
        resp = requests.post(url, files=files, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        
        # Asumsikan n8n mengembalikan {"text": "hasil ocr"}
        text = result.get("text", "")
        if text:
            return extract_best_line(text)
        return None
    except Exception as e:
        print("n8n OCR error:", e)
        return None

@app.route('/ocr-form', methods=['POST'])
def ocr_form():
    try:
        # Ambil file gambar dari form-data
        if 'image' not in request.files:
            return jsonify({"error": "No image file provided"}), 400
            
        image_file = request.files['image']
        
        if image_file.filename == '':
            return jsonify({"error": "No file selected"}), 400

        # Baca file ke memory dan reset pointer
        image_file.seek(0)
        file_content = image_file.read()
        
        # Debug info
        print(f"File size: {len(file_content)} bytes")
        print(f"Filename: {image_file.filename}")
        print(f"Content type: {image_file.mimetype}")

        n8n_webhook_url = "https://mastah.app.n8n.cloud/webhook-test/waan"
        
        # Kirim file asli dalam format binary (JPG/PNG)
        files = {
            'image': (image_file.filename, file_content, image_file.mimetype or 'image/jpeg')
        }

        resp = requests.post(n8n_webhook_url, files=files, timeout=30)
        
        print(f"n8n response status: {resp.status_code}")
        print(f"n8n response: {resp.text}")

        if resp.status_code == 200:
            try:
                resp_json = resp.json()
                return jsonify(resp_json)
            except json.JSONDecodeError:
                return jsonify({
                    "error": "Invalid JSON response from n8n",
                    "response": resp.text[:500]
                }), 500
        else:
            return jsonify({
                "error": f"Webhook n8n gagal, status: {resp.status_code}",
                "detail": resp.text[:500]
            }), 500

    except Exception as e:
        print(f"OCR Form error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/test-n8n-file', methods=['POST'])
def test_n8n_file():
    """Test mengirim file gambar ke n8n dalam format asli"""
    try:
        if 'image' not in request.files:
            return jsonify({"error": "No image file"}), 400
            
        image_file = request.files['image']
        
        # Baca file
        image_file.seek(0)
        file_content = image_file.read()
        
        # Test kirim ke n8n
        url = "https://mastah.app.n8n.cloud/webhook-test/waan"
        files = {
            'image': (image_file.filename, file_content, image_file.mimetype)
        }
        
        resp = requests.post(url, files=files, timeout=15)
        
        return jsonify({
            "status": resp.status_code,
            "response": resp.text,
            "headers": dict(resp.headers),
            "file_info": {
                "filename": image_file.filename,
                "size": len(file_content),
                "mimetype": image_file.mimetype
            }
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5001)
