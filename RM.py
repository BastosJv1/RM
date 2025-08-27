from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime, timedelta
import os
import json
import unicodedata
from thefuzz import fuzz
import fitz
import docx
import pytesseract
from pdf2image import convert_from_path
from PIL import Image, ImageFilter, ImageOps


app = Flask(__name__)
app.secret_key = '04031998'


UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


PASTA_RAIZ = r"\\servidor\12- SETOR DE COMPRAS"
INDICE_FILENAME = 'indice_documentos.json'
INDICE_PATH = os.path.join(PASTA_RAIZ, INDICE_FILENAME)


pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
POPPLER_PATH = r'C:\Program Files\poppler-25.07.0\Library\bin'


USUARIOS = {
    "BastosJv": "040398",
    "LeandroEller": "123456",
    "usuario3": "senha3",
    "usuario4": "senha4",
}


ordens_de_compra = []  # Armazenamento simples para OCs


def pre_process_image(img):
    img = ImageOps.grayscale(img)
    img = ImageOps.autocontrast(img)
    img = img.filter(ImageFilter.SHARPEN)
    return img


def extrair_texto_pdf(caminho):
    texto = ""
    try:
        pdf = fitz.open(caminho)
        for pagina in pdf:
            texto += pagina.get_text()
        if texto.strip() == "":
            imagens = convert_from_path(caminho, dpi=300, poppler_path=POPPLER_PATH)
            ocr_texto = []
            for img in imagens:
                img = pre_process_image(img)
                custom_config = r'--oem 3 --psm 6'
                ocr_texto.append(pytesseract.image_to_string(img, lang="por+eng", config=custom_config))
            texto = "\n".join(ocr_texto)
    except Exception as e:
        print(f"Erro ao ler PDF {caminho}: {e}")
    return texto


def extrair_texto_docx(caminho):
    texto = ""
    try:
        doc = docx.Document(caminho)
        for p in doc.paragraphs:
            texto += p.text + "\n"
    except Exception as e:
        print(f"Erro ao ler DOCX {caminho}: {e}")
    return texto


def extrair_texto_txt(caminho):
    texto = ""
    try:
        with open(caminho, 'r', encoding='utf-8', errors='ignore') as f:
            texto = f.read()
    except Exception as e:
        print(f"Erro ao ler TXT {caminho}: {e}")
    return texto


def extrair_texto_imagem(caminho):
    texto = ""
    try:
        img = Image.open(caminho)
        img = pre_process_image(img)
        custom_config = r'--oem 3 --psm 6'
        texto = pytesseract.image_to_string(img, lang="por+eng", config=custom_config)
    except Exception as e:
        print(f"Erro ao ler imagem {caminho}: {e}")
    return texto


def criar_indice(pasta_raiz, arquivo_json=INDICE_FILENAME, max_preview_length=1000):
    extensoes_suportadas = ['.pdf', '.docx', '.txt', '.jpg', '.jpeg', '.png']
    indice = []
    print("Iniciando criação do índice de documentos com OCR.")
    for root, dirs, files in os.walk(pasta_raiz):
        for file in files:
            if file.startswith("~$"):
                continue
            nome, ext = os.path.splitext(file.lower())
            if ext in extensoes_suportadas:
                caminho_completo = os.path.join(root, file)
                texto_extraido = ""
                if ext == '.pdf':
                    texto_extraido = extrair_texto_pdf(caminho_completo)
                elif ext == '.docx':
                    texto_extraido = extrair_texto_docx(caminho_completo)
                elif ext == '.txt':
                    texto_extraido = extrair_texto_txt(caminho_completo)
                elif ext in ['.jpg', '.jpeg', '.png']:
                    texto_extraido = extrair_texto_imagem(caminho_completo)
                else:
                    continue
                texto_preview = texto_extraido[:max_preview_length] if len(texto_extraido) > max_preview_length else texto_extraido
                indice.append({
                    "caminho": caminho_completo,
                    "nome": file,
                    "ext": ext,
                    "texto": texto_preview
                })
    caminho_json = os.path.join(pasta_raiz, arquivo_json)
    try:
        with open(caminho_json, 'w', encoding='utf-8') as f:
            json.dump(indice, f, ensure_ascii=False, indent=4)
        print(f"Índice criado com {len(indice)} arquivos, salvo em: {caminho_json}")
    except Exception as e:
        print(f"Não foi possível salvar índice em {caminho_json}: {e}")
    return indice


def normalizar_texto(texto):
    nfkd = unicodedata.normalize('NFKD', texto)
    texto_sem_acentos = ''.join([c for c in nfkd if not unicodedata.combining(c)])
    return texto_sem_acentos.lower()


if not os.path.exists(INDICE_PATH):
    try:
        documentos_indexados = criar_indice(PASTA_RAIZ)
    except Exception as e:
        print(f"Falha ao criar índice: {e}")
        documentos_indexados = []
else:
    print("Carregando índice existente...")
    try:
        with open(INDICE_PATH, 'r', encoding='utf-8') as f:
            documentos_indexados = json.load(f)
    except Exception as e:
        print(f"Falha ao carregar índice existente: {e}")
        documentos_indexados = []


def extrair_preview(texto, termo, tam=150):
    texto_lower = texto.lower()
    termo_lower = termo.lower()
    index = texto_lower.find(termo_lower)
    if index == -1:
        return texto[:tam] + "..." if len(texto) > tam else texto
    inicio = max(0, index - tam // 2)
    fim = min(len(texto), index + tam // 2)
    preview = texto[inicio:fim]
    if inicio > 0:
        preview = "..." + preview
    if fim < len(texto):
        preview = preview + "..."
    return preview.replace('\n', ' ').replace('\r', '')


def buscar_arquivos_por_texto(nome_procurado, threshold=60):
    nome_norm = normalizar_texto(nome_procurado.strip())
    resultados = []

    for doc in documentos_indexados:
        nome_arquivo_norm = normalizar_texto(doc["nome"])
        nome_arquivo_sem_ext = os.path.splitext(doc["nome"])[0]
        nome_arquivo_sem_ext_norm = normalizar_texto(nome_arquivo_sem_ext)

        if (nome_norm == nome_arquivo_norm or nome_norm == nome_arquivo_sem_ext_norm or
                nome_norm in nome_arquivo_norm or nome_norm in nome_arquivo_sem_ext_norm):
            preview = extrair_preview(doc['texto'], nome_procurado)
            resultados.append({
                "caminho": doc["caminho"],
                "nome": doc["nome"],
                "exato": True,
                "ext": doc["ext"],
                "preview": preview,
                "tipo": doc["ext"].replace('.', '').upper()
            })

    caminhos_encontrados = set(r['caminho'] for r in resultados)
    for doc in documentos_indexados:
        if doc["caminho"] in caminhos_encontrados:
            continue
        texto_norm = normalizar_texto(doc['texto'])
        if nome_norm in texto_norm:
            preview = extrair_preview(doc['texto'], nome_procurado)
            resultados.append({
                "caminho": doc["caminho"],
                "nome": doc["nome"],
                "exato": True,
                "ext": doc["ext"],
                "preview": preview,
                "tipo": doc["ext"].replace('.', '').upper()
            })

    caminhos_encontrados = set(r['caminho'] for r in resultados)
    for doc in documentos_indexados:
        if doc["caminho"] in caminhos_encontrados:
            continue
        nome_arquivo_norm = normalizar_texto(doc["nome"])
        ratio = fuzz.partial_ratio(nome_norm, nome_arquivo_norm)
        if ratio >= threshold:
            preview = extrair_preview(doc['texto'], nome_procurado)
            resultados.append({
                "caminho": doc["caminho"],
                "nome": doc["nome"],
                "exato": False,
                "ext": doc["ext"],
                "preview": preview,
                "tipo": doc["ext"].replace('.', '').upper()
            })

    resultados.sort(key=lambda x: (not x["exato"], x["nome"].lower()))
    return resultados


class Funcionario:
    def __init__(self, nome, email):
        self.nome = nome
        self.email = email


class Item:
    def __init__(self, descricao, quantidade, anexo_filename=None):
        self.descricao = descricao
        self.quantidade = quantidade
        self.anexo_filename = anexo_filename


class Requisicao:
    def __init__(self, id_req, requisitante, itens):
        self.id_req = id_req
        self.requisitante = requisitante
        self.itens = itens
        self.funcionario_responsavel = None
        self.status = "AGUARDANDO APROVAÇÃO"
        self.historia_status = [(self.status, datetime.now())]
        self.centro_custo = ""
        self.observacoes_comprador = ""
        self.comprador_responsavel = ""
        self.data_conclusao = ""
        self.observacoes_almoxarifado = ""
        self.numero_oc = ""

    def atribuir_funcionario(self, funcionario):
        self.funcionario_responsavel = funcionario

    def atualizar_status(self, novo_status):
        self.status = novo_status
        self.historia_status.append((novo_status, datetime.now()))


funcionarios = [
    Funcionario("Alice Silva", "alice@empresa.com"),
    Funcionario("Bruno Costa", "bruno@empresa.com")
]

requisicoes = []


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form.get("usuario")
        senha = request.form.get("senha")
        if usuario in USUARIOS and USUARIOS[usuario] == senha:
            session["logado"] = True
            session["usuario"] = usuario
            return redirect(url_for("controle"))
        else:
            return render_template("login.html", erro="Usuário ou senha incorretos.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("logado", None)
    session.pop("usuario", None)
    return redirect(url_for("login"))


@app.route("/novo_pedido", methods=["GET", "POST"])
def novo_pedido():
    if request.method == "POST":
        rm = request.form.get("rm")
        if not rm or not rm.isdigit():
            flash("Número RM inválido")
            return redirect(url_for("novo_pedido"))
        id_req = int(rm)

        if any(r.id_req == id_req for r in requisicoes):
            flash("RM já existe. Por favor, atualize a página para obter o próximo número.")
            return redirect(url_for("novo_pedido"))

        requisitante = request.form.get("requisitante")
        descricoes = request.form.getlist("descricao[]")
        especificacoes = request.form.getlist("especificacoes[]")
        unidade_medida = request.form.getlist("unidade_medida[]")
        qtds = request.form.getlist("qtd[]")
        anexos = request.files.getlist("anexo[]")

        itens = []
        for i in range(len(descricoes)):
            desc = descricoes[i]
            qtd = int(qtds[i]) if qtds[i].isdigit() else 1
            espec = especificacoes[i] if i < len(especificacoes) else ""
            unidade = unidade_medida[i] if i < len(unidade_medida) else ""
            arquivo = anexos[i] if i < len(anexos) else None
            filename = None
            if arquivo and arquivo.filename:
                filename = f"rm{id_req}_item{i+1}_" + arquivo.filename
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                arquivo.save(filepath)
            item = Item(desc, qtd, filename)
            item.especificacoes = espec
            item.unidade_medida = unidade
            itens.append(item)

        nova_req = Requisicao(id_req, requisitante, itens)
        requisicoes.append(nova_req)

        flash(f"Requisição RM {id_req} enviada com sucesso ao setor de compras.")
        return redirect(url_for("novo_pedido"))

    proximo_rm = len(requisicoes) + 1
    return render_template("novo_pedido.html", proximo_rm=proximo_rm)


@app.route("/controle", methods=["GET", "POST"])
def controle():
    if not session.get("logado"):
        return redirect(url_for("login"))

    if request.method == "POST":
        rm = request.form.get("rm")
        req = next((r for r in requisicoes if str(r.id_req) == rm), None)
        if req:
            req.status = request.form.get("status_solicitacao", req.status)
            req.centro_custo = request.form.get("centro_custo", req.centro_custo)
            req.observacoes_comprador = request.form.get("obs_comprador", req.observacoes_comprador)
            req.comprador_responsavel = request.form.get("comprador_responsavel", req.comprador_responsavel)
            req.data_conclusao = request.form.get("data_conclusao", req.data_conclusao)
            req.observacoes_almoxarifado = request.form.get("obs_almoxarifado", req.observacoes_almoxarifado)
            req.numero_oc = request.form.get("numero_oc", req.numero_oc)
        return redirect(url_for("controle"))

    return render_template("controle.html", requisicoes=requisicoes)


@app.route("/kanban")
def kanban():
    if not session.get("logado"):
        return redirect(url_for("login"))

    status_categories = [
        "SOLICITAÇÃO APROVADA",
        "COMPRA EFETUADA",
        "EM EXPEDIÇÃO",
        "PEDIDO ENTREGUE"
    ]

    requisicoes_por_status = {status: [] for status in status_categories}
    for r in requisicoes:
        if r.status in requisicoes_por_status:
            requisicoes_por_status[r.status].append(r)

    return render_template("kanban.html", requisicoes_por_status=requisicoes_por_status)


@app.route("/atualizar_status", methods=["POST"])
def atualizar_status():
    if not session.get("logado"):
        return jsonify({"error": "não autorizado"}), 401

    data = request.get_json()
    rm = data.get("rm")
    novo_status = data.get("status")

    req = next((r for r in requisicoes if str(r.id_req) == rm), None)
    if req and novo_status:
        req.atualizar_status(novo_status)
        return jsonify({"success": True})

    return jsonify({"error": "RM ou status inválido"}), 400


@app.route("/busca_arquivos")
def busca_arquivos():
    if not session.get("logado"):
        return redirect(url_for("login"))
    return render_template("busca_arquivos.html")


@app.route('/buscar', methods=['POST'])
def buscar():
    data = request.json
    nome = data.get('nome', '').strip()
    if not nome:
        return jsonify({"quantidade": 0, "resultados": [], "categoria": ""})
    resultados = buscar_arquivos_por_texto(nome, threshold=60)
    if resultados:
        extensoes = set(r['ext'] for r in resultados)
        if any(ext in ['.jpg', '.jpeg', '.png'] for ext in extensoes):
            categoria = "Imagem / OCR"
        elif any(ext == '.pdf' for ext in extensoes):
            categoria = "Documentos PDF"
        elif any(ext == '.docx' for ext in extensoes):
            categoria = "Documentos Word"
        elif any(ext == '.txt' for ext in extensoes):
            categoria = "Textos Simples"
        else:
            categoria = "Outros"
    else:
        categoria = ""
    return jsonify({
        "quantidade": len(resultados),
        "resultados": resultados,
        "categoria": categoria
    })


@app.route("/api/get_rm_data/<int:rm_number>")
def get_rm_data(rm_number):
    if not session.get("logado"):
        return jsonify({"error": "não autorizado"}), 401

    req = next((r for r in requisicoes if r.id_req == rm_number), None)
    if not req:
        return jsonify({"error": "RM não encontrada"}), 404

    dados_oc = {
        "numero_oc": req.numero_oc or "",
        "centro_custo": req.centro_custo or "",
        "descricao": " / ".join([f"{item.descricao} (Qtd: {item.quantidade})" for item in req.itens]) if req.itens else "",
        "obs_almoxarifado": req.observacoes_almoxarifado or "",
        "comprador_responsavel": req.comprador_responsavel or "",
    }

    return jsonify(dados_oc)


@app.route("/oc", methods=["GET", "POST"])
def oc():
    if not session.get("logado"):
        return redirect(url_for("login"))

    if request.method == "POST":
        dados = request.form.to_dict(flat=False)

        descricoes = dados.get('descricao[]', [])
        quantidades = dados.get('quantidade[]', [])
        centros_custo = dados.get('centro_custo', [''])[0]
        previsoes = dados.get('previsao_entrega', [''])[0]
        locais_entrega = dados.get('local_entrega', [''])[0]
        descricao_geral = dados.get('descricao_geral', [''])[0]

        itens = []
        for i in range(len(descricoes)):
            item = {
                'material': descricao_geral,  # Campo 'material' está com a Descrição Geral da OC
                'quantidade': quantidades[i] if i < len(quantidades) else '',
                'centro_custo': centros_custo,
                'previsao_entrega': previsoes,
                'local_entrega': locais_entrega,
            }
            itens.append(item)

        oc_data = {
            'numero_oc': dados.get('numero_oc', [''])[0],
            'itens': itens
        }

        # Atualiza ou adiciona ordem de compra na lista
        for idx, oc in enumerate(ordens_de_compra):
            if oc['numero_oc'] == oc_data['numero_oc']:
                ordens_de_compra[idx] = oc_data
                break
        else:
            ordens_de_compra.append(oc_data)

        flash("Ordem de Compra salva com sucesso.")
        return redirect(url_for("oc"))

    return render_template("oc.html", ordens_de_compra=ordens_de_compra)

@app.route("/almoxarifado/entregas")
def acompanhamento_entregas():
    if not session.get("logado"):
        return redirect(url_for("login"))

    hoje = datetime.now().date()
    itens_para_exibir = []
    alerta_vencido = False
    alerta_proximo = False

    for oc in ordens_de_compra:
        numero_oc = oc.get('numero_oc', '')
        for item in oc.get('itens', []):
            data_texto = item.get('previsao_entrega', '')
            data_formatada = data_texto
            alerta_item = None
            try:
                data_obj = datetime.strptime(data_texto, '%Y-%m-%d').date()
                data_formatada = data_obj.strftime('%d/%m/%Y')
                dias_para_entrega = (data_obj - hoje).days
                if dias_para_entrega < 0:
                    alerta_vencido = True
                    alerta_item = "Vencida"
                elif dias_para_entrega <= 3:
                    alerta_proximo = True
                    alerta_item = "Próxima a vencer"
            except Exception:
                alerta_item = None

            itens_para_exibir.append({
                'numero_oc': numero_oc,
                'material': item.get('material', ''),
                'quantidade': item.get('quantidade', ''),
                'centro_custo': item.get('centro_custo', ''),
                'previsao_entrega': data_formatada,
                'local_entrega': item.get('local_entrega', ''),
                'alerta': alerta_item
            })

    alertas = []
    if alerta_vencido:
        alertas.append("Há entregas com previsão vencida!")
    if alerta_proximo:
        alertas.append("Há entregas próximas do vencimento (até 3 dias).")

    return render_template("acompanhamento_entregas.html", itens=itens_para_exibir, alertas=alertas)

@app.route("/frota/expedicao")
def frota_expedicao():
    if not session.get("logado"):
        return redirect(url_for("login"))

    # Filtra as requisições com status "EM EXPEDIÇÃO"
    rmas_em_expedicao = [r for r in requisicoes if r.status == "EM EXPEDIÇÃO"]

    return render_template("frota_expedicao.html", requisicoes=rmas_em_expedicao)

from flask import send_from_directory
import smtplib
from email.message import EmailMessage

# Lista simulada de fornecedores
fornecedores = [
    {"nome": "Fornecedor A", "email": "fornecedorA@exemplo.com"},
    {"nome": "Fornecedor B", "email": "fornecedorB@exemplo.com"},
    {"nome": "Fornecedor C", "email": "fornecedorC@exemplo.com"},
]

pedidos_cotacao = []  # lista em memória dos pedidos de cotação enviados

@app.route("/pedidos_compras", methods=["GET", "POST"])
def pedidos_compras():
    if not session.get("logado"):
        return redirect(url_for("login"))

    rm_aprovadas = [r for r in requisicoes if r.status == "SOLICITAÇÃO APROVADA"]

    if request.method == "POST":
        rm_number = int(request.form.get("rm_number"))
        fornecedores_emails = request.form.getlist("fornecedores[]")
        prazo_entrega = request.form.get("prazo_entrega")
        condicoes = request.form.get("condicoes")
        observacoes = request.form.get("observacoes")

        rm_obj = next((r for r in requisicoes if r.id_req == rm_number), None)
        if not rm_obj:
            flash("Requisição RM não encontrada.", "error")
            return redirect(url_for("pedidos_compras"))

        pedido = {
            "rm_number": rm_number,
            "fornecedores": fornecedores_emails,
            "prazo_entrega": prazo_entrega,
            "condicoes": condicoes,
            "observacoes": observacoes,
            "itens": [{"descricao": item.descricao, "quantidade": item.quantidade} for item in rm_obj.itens],
            "data_envio": datetime.now().strftime("%d/%m/%Y %H:%M")
        }

        pedidos_cotacao.append(pedido)

        sucesso, erro_email = enviar_email_cotacao(pedido)
        if sucesso:
            flash(f"Pedido de cotação da RM {rm_number} enviado com sucesso!", "success")
            rm_obj.atualizar_status("APENAS COTAÇÃO")
        else:
            flash(f"Erro ao enviar email: {erro_email}", "error")

        return redirect(url_for("pedidos_compras"))

    return render_template(
        "pedidos_compras.html",
        rm_aprovadas=rm_aprovadas,
        fornecedores=fornecedores,
        pedidos_cotacao=pedidos_cotacao,
        pagina_ativa="pedidos_compras"  # variável para controle da active class
    )



def enviar_email_cotacao(pedido):
    """
    Função simples para enviar emails para fornecedores.
    Altere com o SMTP do seu servidor de email.
    """
    try:
        smtp_server = "smtp.exemplo.com"
        smtp_port = 587
        smtp_user = "usuario@exemplo.com"
        smtp_password = "senha"

        msg = EmailMessage()
        msg['From'] = smtp_user
        msg['To'] = ", ".join(pedido['fornecedores'])
        msg['Subject'] = f"Pedido de Cotação - RM {pedido['rm_number']}"

        # Monta corpo do email
        itens_texto = "\n".join([f"- {i['quantidade']} x {i['descricao']}" for i in pedido['itens']])
        corpo = f"""
Prezado fornecedor,

Solicitamos cotação para os seguintes itens da Requisição RM {pedido['rm_number']}:

{itens_texto}

Prazo de entrega desejado: {pedido['prazo_entrega']}
Condições comerciais: {pedido['condicoes']}

Observações:
{pedido['observacoes']}

Favor enviar sua proposta o mais rápido possível.

Atenciosamente,
Setor de Compras
        """

        msg.set_content(corpo)

        # Abrir conexão SMTP e enviar
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)

        return True, None
    except Exception as e:
        print(f"Erro ao enviar email: {e}")
        return False, str(e)


if __name__ == '__main__':
    # debug=True apenas para desenvolvimento
    app.run(host='0.0.0.0', port=5000, debug=True)
