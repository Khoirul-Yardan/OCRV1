let imageBase64 = "";

document.getElementById("imageInput").addEventListener("change", function (event) {
    const file = event.target.files[0];
    const reader = new FileReader();
    reader.onload = function (e) {
        imageBase64 = e.target.result;
        const preview = document.getElementById("preview");
        preview.src = imageBase64;
        preview.style.display = "block";
    };
    reader.readAsDataURL(file);
});

function sendToOCR() {
    fetch("http://localhost:5000/ocr", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ image: imageBase64 }),
    })
    .then((res) => res.json())
    .then((data) => {
        document.getElementById("result").style.display = "block";
        document.getElementById("namaProduk").value = data.nama || "";
        document.getElementById("hargaBeli").value = data.hargaBeli || "";
        document.getElementById("hargaJual").value = data.hargaJual || "";
        document.getElementById("barcode").value = data.barcode || "";
    });
}

function saveData() {
    const data = {
        nama: document.getElementById("namaProduk").value,
        hargaBeli: document.getElementById("hargaBeli").value,
        hargaJual: document.getElementById("hargaJual").value,
        barcode: document.getElementById("barcode").value,
    };

    fetch("http://localhost:5000/save", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify(data),
    }).then(() => {
        alert("Data disimpan!");
        location.reload();
    });
}

function cancelData() {
    document.getElementById("result").style.display = "none";
}