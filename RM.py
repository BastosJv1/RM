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
import random
from flask import send_file
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import io


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
    def __init__(self, id_req, requisitante, itens, finalidade=""):
        self.id_req = id_req
        self.requisitante = requisitante
        self.itens = itens
        self.funcionario_responsavel = None
        self.status = "AGUARDANDO APROVAÇÃO"
        self.finalidade = finalidade  
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
        centro_custo = request.form.get("centro_custo", "")
        descricoes = request.form.getlist("descricao[]")
        especificacoes = request.form.getlist("especificacoes[]")
        unidade_medida = request.form.getlist("unidade_medida[]")
        qtds = request.form.getlist("qtd[]")
        finalidade = request.form.get('finalidade')
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

        nova_req = Requisicao(id_req, requisitante, itens, finalidade=finalidade)
        nova_req.centro_custo = centro_custo  # adicionando o centro de custo
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


from flask import jsonify

@app.route('/api/rms')
def api_rms():
    # Aqui você retorna todas as RMs disponíveis, filtrando por status se necessário
    rms_disponiveis = [
        {
            "id_req": r.id_req,
            "requisitante": r.requisitante,
            "itens": [{"descricao": i.descricao, "quantidade": i.quantidade, "unidade_medida": i.unidade_medida, "especificacoes": i.especificacoes} for i in r.itens],
            "centro_custo": r.centro_custo,
            "finalidade": r.finalidade,
            "observacoes_almoxarifado": r.observacoes_almoxarifado
        }
        for r in requisicoes if r.status not in ["PEDIDO ENTREGUE", "PEDIDO CANCELADO"]
    ]
    return jsonify(rms_disponiveis)


@app.route("/oc", methods=["GET", "POST"])
def oc():
    if not session.get("logado"):
        return redirect(url_for("login"))

    if request.method == "POST":
        numero_oc = request.form.get("numero_oc")  # vem oculto do form
        data_solicitacao = request.form.get("data_solicitacao")
        descricao_geral = request.form.get("descricao_geral")
        dados = request.form.to_dict(flat=False)
        descricoes = dados.get('descricao[]', [])
        quantidades = dados.get('quantidade[]', [])
        precos_unitarios = dados.get('preco_unitario[]', [])

        for i in range(len(descricoes)):
            preco_str = precos_unitarios[i] if i < len(precos_unitarios) else "R$ 0,00"
            preco_num = 0.0
            try:
                preco_num = float(preco_str.replace('R$', '').replace('.', '').replace(',', '.').strip())
            except:
                pass

            item = {
                "numero_oc": numero_oc,
                "descricao": descricoes[i],
                "quantidade": quantidades[i] if i < len(quantidades) else "",
                "preco_unitario": preco_num,
                "data_solicitacao": data_solicitacao,
                "descricao_geral": descricao_geral,
                "categoria": dados.get("categoria", [""])[0],
                "centro_custo": dados.get("centro_custo", [""])[0],
                "fornecedor": dados.get("fornecedor", [""])[0],
                "previsao_entrega": dados.get("previsao_entrega", [""])[0],
                "local_entrega": dados.get("local_entrega", [""])[0],
                "baixa": False,  # Baixa do Almoxarifado.
                "obs": dados.get("obs", [""])[0],
                "condicoes_entrega": dados.get("condicoes_entrega", [""])[0],
                "tipo_frete": dados.get("tipo_frete", [""])[0],
                "obs_almoxarifado": dados.get("obs_almoxarifado", [""])[0],
                "status_entrega": dados.get("status_entrega", [""])[0],
                "nf": dados.get("nf", [""])[0],
                "natureza_nf": dados.get("natureza_nf", [""])[0],
                "valor_inicial_proposta": parse_moeda(dados.get("valor_inicial_proposta", [""])[0]),
                "valor_final_proposta": parse_moeda(dados.get("valor_final_proposta", [""])[0]),
                "link_nf": dados.get("link_nf", [""])[0]
            }

            ordens_de_compra.append(item)

        flash(f"Ordem de Compra {numero_oc} criada com {len(descricoes)} itens.")
        return redirect(url_for("oc"))

    # Gera número novo toda vez que abre o form
    numero_oc = gerar_numero_oc()
    return render_template("oc.html", numero_oc=numero_oc, ordens_de_compra=ordens_de_compra)

# Página Lista das OC's
@app.route("/ocs")
def lista_ocs():
    if not session.get("logado"):
        return redirect(url_for("login"))

    # Ordena as OCs pelo número
    ordens_ordenadas = sorted(ordens_de_compra, key=lambda x: x['numero_oc'])
    return render_template("lista_ocs.html", ordens_de_compra=ordens_ordenadas)

def gerar_numero_oc():
    ano = datetime.now().year
    prefixo = f"OC-{ano}-"
    # Extrai números já existentes, remove prefixo e pega número sequencial máximo
    numeros_existentes = [
        int(oc['numero_oc'].replace(prefixo, ''))
        for oc in ordens_de_compra
        if oc['numero_oc'].startswith(prefixo) and oc['numero_oc'].replace(prefixo, '').isdigit()
    ]
    proximo_numero = max(numeros_existentes) + 1 if numeros_existentes else 1
    return prefixo + str(proximo_numero).zfill(4)

def parse_moeda(valor_str):
    if not valor_str:
        return 0.0
    try:
        return float(valor_str.replace("R$", "").replace(".", "").replace(",", ".").strip())
    except:
        return 0.0

# Editar a Lista de OC's se necessário.
@app.route("/update_oc", methods=["POST"])
def update_oc():
    if not session.get("logado"):
        return jsonify({"error":"não autorizado"}), 401

    data = request.get_json()
    numero_oc = data.get("numero_oc")
    field = data.get("field")
    value = data.get("value")

    oc = next((o for o in ordens_de_compra if o['numero_oc'] == numero_oc), None)
    if not oc:
        return jsonify({"success": False, "error":"OC não encontrada"})

    # Atualiza o campo
    if field in oc:
        oc[field] = value
        return jsonify({"success": True})

    return jsonify({"success": False, "error":"Campo inválido"})


@app.route("/almoxarifado/entregas")
def acompanhamento_entregas():
    if not session.get("logado"):
        return redirect(url_for("login"))

    hoje = datetime.now().date()
    itens_para_exibir = []
    alerta_vencido = False
    alerta_proximo = False

    # Cria um dicionário para localizar RM pela OC, se existir
    rm_por_oc = {r.numero_oc: r for r in requisicoes if r.numero_oc}

    # 1️⃣ Itens das OCs
    for oc in ordens_de_compra:
        numero_oc = oc.get('numero_oc', '')
        previsao = oc.get('previsao_entrega', '').strip()
        
        # Pula OC se já recebeu baixa
        if oc.get('baixa', False):
            continue

        if previsao:
            rm_relacionada = rm_por_oc.get(numero_oc)
            if rm_relacionada and rm_relacionada.data_conclusao:
                continue

            data_formatada = previsao
            alerta_item = None
            try:
                data_obj = datetime.strptime(previsao, '%Y-%m-%d').date()
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
                'material': oc.get('descricao', ''),
                'quantidade': oc.get('quantidade', ''),
                'centro_custo': oc.get('centro_custo', ''),
                'previsao_entrega': data_formatada,
                'local_entrega': oc.get('local_entrega', ''),
                'alerta': alerta_item
            })

    alertas = []
    if alerta_vencido:
        alertas.append("Há entregas com previsão vencida!")
    if alerta_proximo:
        alertas.append("Há entregas próximas do vencimento (até 3 dias).")

    return render_template("acompanhamento_entregas.html", itens=itens_para_exibir, alertas=alertas)

# Baixa na Entrega do Almoxarifado.
@app.route("/almoxarifado/entregas/baixa/<numero_oc>", methods=["POST"])
def dar_baixa_entrega(numero_oc):
    if not session.get("logado"):
        return jsonify({"error": "não autorizado"}), 401

    # Marca como baixa os itens da OC
    for oc in ordens_de_compra:
        if oc.get('numero_oc', '') == numero_oc and not oc.get('baixa', False):
            oc['baixa'] = True  # marca como entregue

    # Atualiza o status da RM correspondente
    rm_relacionada = next((r for r in requisicoes if r.numero_oc == numero_oc), None)
    if rm_relacionada:
        rm_relacionada.status = "PEDIDO ENTREGUE"

    return jsonify({"success": True})


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
    {"nome": "Fornecedor A", "email": "fornecedorA@email.com"},
    {"nome": "Fornecedor B", "email": "fornecedorB@email.com"}
]

# Rota para cadastrar fornecedores
@app.route("/fornecedores", methods=["GET", "POST"])
def fornecedores_view():
    if not session.get("logado"):
        return redirect(url_for("login"))

    return render_template(
        "fornecedores.html",
        fornecedores=fornecedores,
        pagina_ativa="fornecedores"
    )

fornecedores = []        # sua lista de fornecedores
pedidos_cotacao = []     # lista de pedidos de cotação enviados
rm_aprovadas = []        # lista de RMs aprovadas (se você já usa)

# Adicionar fornecedor
@app.route("/adicionar_fornecedor", methods=["POST"])
def adicionar_fornecedor():
    nome = request.form["nome"]
    email = request.form["email"]
    
    # Adiciona ao seu "banco" (ou lista)
    fornecedores.append({"nome": nome, "email": email})
    
    # Mensagem de sucesso
    flash("Fornecedor adicionado com sucesso!", "success")
    
    # Redireciona de volta para a página de onde veio (pedidos_compras)
    return redirect(request.referrer or url_for("pedidos_compras"))

# Excluir fornecedor mantendo na mesma página
@app.route("/fornecedores/excluir/<email>", methods=["POST"])
def excluir_fornecedor(email):
    if not session.get("logado"):
        return redirect(url_for("login"))

    global fornecedores
    fornecedores = [f for f in fornecedores if f["email"] != email]

    flash("Fornecedor removido com sucesso!", "success")
    # Redireciona de volta para a página de onde veio o POST
    return redirect(request.referrer or url_for("pedidos_compras"))


from flask import send_file
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import io

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

        # Cria PDF em memória
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        largura, altura = A4

        y = altura - 50
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, y, f"Pedido de Cotação - RM {rm_number}")
        y -= 30

        c.setFont("Helvetica", 12)
        c.drawString(50, y, f"Requisitante: {rm_obj.requisitante}")
        y -= 20
        c.drawString(50, y, f"Fornecedores Selecionados: {', '.join(fornecedores_emails)}")
        y -= 20
        c.drawString(50, y, f"Prazo de Entrega Desejado: {prazo_entrega}")
        y -= 20
        c.drawString(50, y, f"Condições Comerciais: {condicoes}")
        y -= 20
        c.drawString(50, y, f"Observações: {observacoes}")
        y -= 40

        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, "Itens Solicitados:")
        y -= 20
        c.setFont("Helvetica", 11)
        for item in rm_obj.itens:
            c.drawString(60, y, f"- {item.quantidade} x {item.descricao}")
            y -= 18
            if y < 80:
                c.showPage()
                y = altura - 50

        c.showPage()
        c.save()
        buffer.seek(0)

        # Atualiza status
        rm_obj.atualizar_status("APENAS COTAÇÃO")

        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"Pedido_Cotacao_RM{rm_number}.pdf",
            mimetype="application/pdf"
        )

    return render_template(
        "pedidos_compras.html",
        rm_aprovadas=rm_aprovadas,
        fornecedores=fornecedores,
        pedidos_cotacao=pedidos_cotacao,
        pagina_ativa="pedidos_compras"
    )

if __name__ == '__main__':
    # debug=True apenas para desenvolvimento
    app.run(host='0.0.0.0', port=5000, debug=True)
