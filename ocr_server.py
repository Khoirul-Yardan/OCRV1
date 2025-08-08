from flask import Flask, request, jsonify, render_template, send_file, make_response
from flask_cors import CORS
import base64
from PIL import Image
import pytesseract
import io
import json
import random
import csv
from io import StringIO, BytesIO
from openpyxl import Workbook
import openai

app = Flask(__name__)
CORS(app)

# 🔐 GANTI dengan API KEY milikmu sendiri
openai.api_key = "api"

@app.route('/')
def index():
    return render_template("index.html")

# ✨ Fungsi untuk dapatkan estimasi harga dari OpenAI
def get_price_estimate(nama_produk):
    prompt = f"""
    Kamu adalah sistem yang memberikan estimasi harga produk di pasaran Indonesia.

    Produk: {nama_produk}
    Tampilkan jawaban dalam format JSON:
    {{
      "hargaBeli": <harga_beli>,
      "hargaJual": <harga_jual>
    }}
    """

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Kamu adalah asisten untuk memperkirakan harga produk di Indonesia."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
        )

        text = response.choices[0].message.content.strip()
        return json.loads(text)

    except Exception as e:
        print("Gagal mengambil harga dari AI:", e)
        return {
            "hargaBeli": random.randint(5000, 15000),
            "hargaJual": random.randint(16000, 30000)
        }

@app.route('/ocr', methods=['POST'])
def ocr():
    data = request.get_json()
    image_data = base64.b64decode(data['image'].split(',')[1])
    image = Image.open(io.BytesIO(image_data))

    text = pytesseract.image_to_string(image)
    nama_produk = text.strip().split('\n')[0] or "Produk A"

    # ✨ Dapatkan harga dari AI
    harga_data = get_price_estimate(nama_produk)

    return jsonify({
        "nama": nama_produk,
        "hargaBeli": harga_data["hargaBeli"],
        "hargaJual": harga_data["hargaJual"],
        "barcode": "BR" + str(random.randint(100000, 999999))
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

from openai import OpenAI

# Inisialisasi klien
client = OpenAI(api_key="api")  # Ganti dengan API key kamu

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
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "Kamu adalah asisten yang menjawab pertanyaan tentang aplikasi pemindai produk dan harga pasar."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.4,
        )
        answer = response.choices[0].message.content.strip()
    except Exception as e:
        print("Chatbot error:", e)
        answer = "Maaf, saya tidak bisa menjawab sekarang."

    return jsonify({"answer": answer})

if __name__ == '__main__':
    app.run(debug=True)
