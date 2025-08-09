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
GEMINI_API_KEY = "AIzaSyA88MN3DtkhqapsjTmNhEoE92n9GAdWBTI"
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
        model = genai.GenerativeModel("gemini-1.5-flash")
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

    # 1. Coba EasyOCR dulu
    nama_produk = ocr_with_easyocr(image)
    # 2. Jika gagal, fallback ke Tesseract (tanpa whitelist)
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

    si = StringIO()
    writer = csv.DictWriter(si, fieldnames=["nama", "hargaBeli", "hargaJual", "barcode"])
    writer.writeheader()
    writer.writerows(data)

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=produk.csv"
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

    # 1. Coba EasyOCR dulu
    nama_produk = ocr_with_easyocr(image)
    # 2. Jika gagal, fallback ke Tesseract
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

if __name__ == '__main__':
    app.run(debug=True)
