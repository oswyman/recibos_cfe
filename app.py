from flask import Flask, request, render_template, redirect, url_for, flash, session, send_file
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
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Límite de tamaño de archivo: 16 MB
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'supersecretkey')

csrf = CSRFProtect(app)

openai.api_key = os.getenv('OPENAI_API_KEY')

if openai.api_key is None or openai.api_key.startswith("sk-YOUR"):
    raise ValueError("No API key found or incorrect API key provided. Please set the OPENAI_API_KEY in touch.env")

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

def extract_info_from_text(text):
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
    extracted_content = response.choices[0].message['content'].strip()
    
    # Clean potential code blocks and ensure valid JSON format
    if extracted_content.startswith("```json"):
        extracted_content = extracted_content[7:].strip()
    if extracted_content.endswith("```"):
        extracted_content = extracted_content[:-3].strip()

    return extracted_content

def parse_extracted_info(info):
    try:
        info_cleaned = info.strip()
        if info_cleaned.startswith('{') and info_cleaned.endswith('}'):
            data = json.loads(info_cleaned)
        else:
            raise ValueError("Invalid JSON format")
        datos_cliente = data.get("DATOS DEL CLIENTE", {})
        datos_lectura = data.get("DATOS DE LECTURA", {})
        costos_energia = data.get("COSTOS DE LA ENERGÍA EN EL MERCADO ELECTRICO MAYORISTA", {})
        desglose_importe = data.get("DESGLOSE DEL IMPORTE A PAGAR", {})
        consumo_historico = data.get("TABLA CONSUMO HISTORICO", [])
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error decoding JSON: {e}")
        datos_cliente = datos_lectura = costos_energia = desglose_importe = {}
        consumo_historico = []

    return datos_cliente, datos_lectura, costos_energia, desglose_importe, consumo_historico

@app.route('/', methods=['GET', 'POST'])
def index():
    form = UploadForm()
    if form.validate_on_submit():
        files = form.files.data
        extracted_data = []
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
            text = extract_text_from_pdf(file_path)
            info = extract_info_from_text(text)
            datos_cliente, datos_lectura, costos_energia, desglose_importe, consumo_historico = parse_extracted_info(info)
            extracted_data.append({
                'datos_cliente': datos_cliente,
                'datos_lectura': datos_lectura,
                'costos_energia': costos_energia,
                'desglose_importe': desglose_importe,
                'consumo_historico': consumo_historico
            })
            filenames.append(filename)
        session['extracted_data'] = extracted_data
        session['filenames'] = filenames
        return redirect(url_for('results', page=1))
    return render_template('index.html', form=form)

@app.route('/results/<int:page>')
def results(page):
    data = session.get('extracted_data', [])
    filenames = session.get('filenames', [])
    if not data or not filenames:
        return redirect(url_for('index'))
    total_pages = len(data)
    if page < 1 or page > total_pages:
        return redirect(url_for('results', page=1))
    receipt = data[page - 1]
    filename = filenames[page - 1]
    return render_template('results.html', receipt=receipt, page=page, total_pages=total_pages, filename=filename)

@app.route('/download/<int:page>')
def download(page):
    data = session.get('extracted_data', [])
    filenames = session.get('filenames', [])
    if not data or page < 1 or page > len(data):
        return redirect(url_for('index'))

    receipt = data[page - 1]
    filename = filenames[page - 1].replace('.pdf', '.xlsx')
    
    df_cliente = pd.DataFrame([receipt['datos_cliente']])
    df_lectura = pd.DataFrame([receipt['datos_lectura']])
    df_costos = pd.DataFrame([receipt['costos_energia']])
    df_importe = pd.DataFrame([receipt['desglose_importe']])
    df_consumo = pd.DataFrame(receipt['consumo_historico'])

    excel_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
        df_cliente.to_excel(writer, sheet_name='Datos del Cliente', index=False)
        df_lectura.to_excel(writer, sheet_name='Datos de Lectura', index=False)
        df_costos.to_excel(writer, sheet_name='Costos de Energía', index=False)
        df_importe.to_excel(writer, sheet_name='Desglose de Importe', index=False)
        df_consumo.to_excel(writer, sheet_name='Consumo Histórico', index=False)

    return send_file(excel_path, as_attachment=True)

if __name__ == '__main__':
    if not os.path.exists('uploads'):
        os.makedirs('uploads')
    app.run()
