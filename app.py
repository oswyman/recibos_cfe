from flask import Flask, request, render_template, redirect, url_for, flash, session
from celery import Celery
import openai
from PyPDF2 import PdfReader
import os
import json
import pandas as pd
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect
from flask_wtf import FlaskForm
from wtforms import MultipleFileField, SubmitField

load_dotenv('touch.env')

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'supersecretkey')

csrf = CSRFProtect(app)

openai.api_key = os.getenv('OPENAI_API_KEY')

celery = Celery(app.name, broker='redis://localhost:6379/0')

class UploadForm(FlaskForm):
    files = MultipleFileField('Sube tus archivos PDF')
    submit = SubmitField('Subir y Procesar')

def extract_text_from_pdf(pdf_path):
    with open(pdf_path, 'rb') as file:
        reader = PdfReader(file)
        text = ''
        for page in reader.pages:
            text += page.extract_text()
    return text

@celery.task
def process_pdf(file_path):
    text = extract_text_from_pdf(file_path)
    prompt = f"""
    Extract the following information from the CFE receipt and provide the data clearly and structured in JSON format:

    {{
        "DATOS DEL CLIENTE": {{
            "NOMBRE DEL SERVICIO": "",
            "NUMERO DEL SERVICIO": "",
            "CIUDAD": "",
            "ESTADO": "",
            "TARIFA": "",
            "NO. MEDIDOR": "",
            "MULTIPLICADOR": "",
            "PERIODO FACTURADO": ""
        }},
        "DATOS DE LECTURA": {{
            "LECTURA ACTUAL": "",
            "LECTURA ANTERIOR": "",
            "TOTAL PERIODO": "",
            "PRECIO": "",
            "SUBTOTAL": ""
        }},
        "COSTOS DE LA ENERGÍA EN EL MERCADO ELECTRICO MAYORISTA": {{
            "SUMINISTRO": "",
            "DISTRIBUCIÓN": "",
            "TRANSMISIÓN": "",
            "CENACE": "",
            "ENERGIA": "",
            "CAPACIDAD": "",
            "SCNMEM": "",
            "TOTAL": ""
        }},
        "DESGLOSE DEL IMPORTE A PAGAR": {{
            "CARGO FIJO": "",
            "ENERGIA": "",
            "SUBTOTAL": "",
            "IVA": "",
            "FAC. DEL PERIODO": "",
            "DAP": "",
            "TOTAL": ""
        }},
        "TABLA CONSUMO HISTORICO": [
            {{
                "PERIODO": "",
                "KWH": "",
                "IMPORTE": "",
                "PAGOS": ""
            }}
        ]
    }}

    Use the provided text to extract the information:

    {text}
    """
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message['content'].strip()

@app.route('/', methods=['GET', 'POST'])
def index():
    form = UploadForm()
    if form.validate_on_submit():
        files = form.files.data
        filenames = []
        for file in files:
            if file.filename == '':
                flash('No selected file')
                return redirect(url_for('index'))
            if not file.filename.lower().endswith('.pdf'):
                flash(f'File {file.filename} is not a PDF')
                continue
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            process_pdf.delay(file_path)
            filenames.append(filename)
        session['filenames'] = filenames
        flash('Archivos subidos y procesados en segundo plano.')
        return redirect(url_for('index'))
    return render_template('index.html', form=form)

if __name__ == '__main__':
    if not os.path.exists('uploads'):
        os.makedirs('uploads')
    app.run()
