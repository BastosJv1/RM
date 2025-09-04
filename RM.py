from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from datetime import datetime
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
import io
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import psycopg2

app = Flask(__name__)
app.secret_key = '04031998'


UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

ordens_de_compra = []  # Armazenamento simples para OCs

DB_CONFIG = {
    "host": "dpg-d2sr8aodl3ps73ek9m5g-a.oregon-postgres.render.com",
    "port": 5432,
    "dbname": "sistema3r",
    "user": "sistema3r_user",
    "password": "XXFxreI1QJ0NbAqrMSVUcPiYa62rEXHH"
}

def get_db_connection():
    conn = psycopg2.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        dbname=DB_CONFIG["dbname"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"]
    )
    return conn

# Criação das tabelas (executar uma vez)
def criar_tabelas():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS requisicoes (
        id_req SERIAL PRIMARY KEY,
        requisitante TEXT,
        finalidade TEXT,
        centro_custo TEXT,
        status TEXT,
        comprador_responsavel TEXT,
        data_conclusao TEXT,
        observacoes_almoxarifado TEXT,
        numero_oc TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS itens_requisicao (
        id SERIAL PRIMARY KEY,
        id_req INTEGER REFERENCES requisicoes(id_req),
        descricao TEXT,
        quantidade INTEGER,
        unidade_medida TEXT,
        especificacoes TEXT,
        anexo_filename TEXT
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS ordens_de_compra (
        id SERIAL PRIMARY KEY,
        numero_oc TEXT,
        descricao TEXT,
        quantidade TEXT,
        preco_unitario NUMERIC,
        data_solicitacao TEXT,
        descricao_geral TEXT,
        categoria TEXT,
        centro_custo TEXT,
        fornecedor TEXT,
        previsao_entrega TEXT,
        local_entrega TEXT,
        baixa BOOLEAN,
        obs TEXT,
        condicoes_entrega TEXT,
        tipo_frete TEXT,
        obs_almoxarifado TEXT,
        status_entrega TEXT,
        nf TEXT,
        natureza_nf TEXT,
        valor_inicial_proposta NUMERIC,
        valor_final_proposta NUMERIC,
        link_nf TEXT
    );
    """)
    conn.commit()
    cur.close()
    conn.close()

criar_tabelas()

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
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
                ocr_texto = [pytesseract.image_to_string(pre_process_image(img), lang="por+eng", config=r'--oem 3 --psm 6') for img in imagens]
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
            texto = pytesseract.image_to_string(pre_process_image(img), lang="por+eng", config=r'--oem 3 --psm 6')
        except Exception as e:
            print(f"Erro ao ler imagem {caminho}: {e}")
        return texto

def normalizar_texto(texto):
        nfkd = unicodedata.normalize('NFKD', texto)
        return ''.join([c for c in nfkd if not unicodedata.combining(c)]).lower()


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
    def __init__(self, descricao, quantidade, anexo_filename=None, observacoes=None):
        self.descricao = descricao
        self.quantidade = quantidade
        self.anexo_filename = anexo_filename
        self.observacoes = observacoes

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
        # Atualiza no banco
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE requisicoes SET status=%s WHERE id_req=%s", (novo_status, self.id_req))
        conn.commit()
        cur.close()
        conn.close()

funcionarios = [
    Funcionario("Alice Silva", "alice@empresa.com"),
    Funcionario("Bruno Costa", "bruno@empresa.com")
]

# ============================
# Funções para OCs no banco
# ============================
def salvar_oc_db(oc):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO ordens_de_compra (
            numero_oc, descricao, quantidade, preco_unitario, data_solicitacao,
            descricao_geral, categoria, centro_custo, fornecedor, previsao_entrega,
            local_entrega, baixa, obs, condicoes_entrega, tipo_frete,
            obs_almoxarifado, status_entrega, nf, natureza_nf, valor_inicial_proposta,
            valor_final_proposta, link_nf
        ) VALUES (
            %(numero_oc)s, %(descricao)s, %(quantidade)s, %(preco_unitario)s, %(data_solicitacao)s,
            %(descricao_geral)s, %(categoria)s, %(centro_custo)s, %(fornecedor)s, %(previsao_entrega)s,
            %(local_entrega)s, %(baixa)s, %(obs)s, %(condicoes_entrega)s, %(tipo_frete)s,
            %(obs_almoxarifado)s, %(status_entrega)s, %(nf)s, %(natureza_nf)s, %(valor_inicial_proposta)s,
            %(valor_final_proposta)s, %(link_nf)s
        );
    """, oc)
    conn.commit()
    cur.close()
    conn.close()

def carregar_ocs_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM ordens_de_compra;")
    linhas = cur.fetchall()
    colunas = [desc[0] for desc in cur.description]
    ocs = []
    for linha in linhas:
        ocs.append(dict(zip(colunas, linha)))
    cur.close()
    conn.close()
    return ocs

# Carrega OCs ao iniciar app
ordens_de_compra = carregar_ocs_db()

def salvar_requisicao_db(requisicao: Requisicao):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO requisicoes (id_req, requisitante, finalidade, status, centro_custo)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (id_req) DO NOTHING;
    """, (requisicao.id_req, requisicao.requisitante, requisicao.finalidade, requisicao.status, requisicao.centro_custo))
    for item in requisicao.itens:
        cur.execute("""
            INSERT INTO itens_requisicao (id_req, descricao, quantidade, unidade_medida, especificacoes, anexo_filename)
            VALUES (%s, %s, %s, %s, %s, %s);
        """, (requisicao.id_req, item.descricao, item.quantidade, getattr(item, "unidade_medida", ""), getattr(item, "especificacoes", ""), item.anexo_filename))
    conn.commit()
    cur.close()
    conn.close()



def carregar_requisicoes_db():
    requisicoes_lista = []
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id_req, requisitante, finalidade, centro_custo, status, comprador_responsavel, data_conclusao, observacoes_almoxarifado, numero_oc FROM requisicoes;")
    linhas = cur.fetchall()
    for linha in linhas:
        id_req, requisitante, finalidade, centro_custo, status, comprador_responsavel, data_conclusao, obs_alm, numero_oc = linha
        cur.execute("SELECT descricao, quantidade, unidade_medida, especificacoes, anexo_filename FROM itens_requisicao WHERE id_req=%s", (id_req,))
        itens_db = cur.fetchall()
        itens = []
        for d in itens_db:
            i = Item(d[0], d[1], d[4] if len(d) > 4 else None)
            i.unidade_medida = d[2]
            i.especificacoes = d[3]
            itens.append(i)
        r = Requisicao(id_req, requisitante, itens, finalidade)
        r.centro_custo = centro_custo
        r.status = status
        r.comprador_responsavel = comprador_responsavel
        r.data_conclusao = data_conclusao
        r.observacoes_almoxarifado = obs_alm
        r.numero_oc = numero_oc
        requisicoes_lista.append(r)
    cur.close()
    conn.close()
    return requisicoes_lista

# Carrega requisicoes ao iniciar app
requisicoes = carregar_requisicoes_db()
ordens_de_compra = []  # Você pode migrar depois para tabela OC

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
        salvar_requisicao_db(nova_req)
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
        req = next((r for r in requisicoes if str(r.id_req) == str(rm)), None)
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

# Atualizar Status Através do Almoxarifado e dar baixa.
@app.route("/atualizar_status", methods=["POST"])
def atualizar_status():
    if not session.get("logado"):
        return jsonify({"error": "não autorizado"}), 401

    data = request.get_json()
    rm = data.get("rm")
    novo_status = data.get("status")

    if not novo_status:
        return jsonify({"error": "Status inválido"}), 400

    # Procura por RM numérica
    req = next((r for r in requisicoes if str(r.id_req) == str(rm)), None)
    # Se não encontrar, tenta procurar por OC
    if not req:
        req = next((r for r in requisicoes if r.numero_oc == str(rm)), None)

    if req:
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
        numero_oc = request.form.get("numero_oc")  # número da OC
        data_solicitacao = request.form.get("data_solicitacao")
        descricao_geral = request.form.get("descricao_geral")
        dados = request.form.to_dict(flat=False)
        descricoes = dados.get("descricao[]", [])
        quantidades = dados.get("quantidade[]", [])
        precos_unitarios = dados.get("preco_unitario[]", [])
        
        # Vínculo da OC com a RM
        rm_referencia = request.form.get("rm_referencia")
        if rm_referencia:
            rm_obj = next((r for r in requisicoes if str(r.id_req) == str(rm_referencia)), None)
            if rm_obj:
                rm_obj.numero_oc = numero_oc

        for i in range(len(descricoes)):
            preco_str = precos_unitarios[i] if i < len(precos_unitarios) else "R$ 0,00"
            preco_num = 0.0
            try:
                preco_num = float(preco_str.replace("R$", "").replace(".", "").replace(",", ".").strip())
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
                "baixa": False,
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
            # Salva cada item da OC no banco
            salvar_oc_db(item)


        flash(f"Ordem de Compra {numero_oc} criada com {len(descricoes)} itens.", "success")
        return redirect(url_for("oc"))

    numero_oc = gerar_numero_oc()
    return render_template("oc.html", numero_oc=numero_oc, ordens_de_compra=ordens_de_compra)

# Página Lista das OC's
@app.route("/ocs")
def lista_ocs():
    if not session.get("logado"):
        return redirect(url_for("login"))

    ordens_ordenadas = sorted(ordens_de_compra, key=lambda x: x['numero_oc'])
    return render_template("lista_ocs.html", ordens_de_compra=ordens_ordenadas)

def gerar_numero_oc():
    ano = datetime.now().year
    prefixo = f"OC-{ano}-"
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

    # Itens das OCs
    for oc in ordens_de_compra:
        numero_oc = oc.get('numero_oc', '')
        previsao = oc.get('previsao_entrega', '').strip()
        
        # Pula OC se já recebeu baixa
        if oc.get('baixa', False):
            continue

        # Localiza a RM relacionada
        rm_relacionada = rm_por_oc.get(numero_oc)
        if rm_relacionada and rm_relacionada.data_conclusao:
            continue

        # Processa previsão de entrega e alertas
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

        # Inicializa a lista de itens antes de qualquer condição
        itens_rm = []

        if rm_relacionada:
            for item_rm in rm_relacionada.itens:
                itens_rm.append({
                    "descricao": item_rm.descricao,
                    "quantidade": item_rm.quantidade,
                    "unidade_medida": getattr(item_rm, "unidade_medida", ""),
                    "chegado": getattr(item_rm, "chegado", False),
                    "quantidade_ok": getattr(item_rm, "quantidade_ok", True),
                    "qualidade_ok": getattr(item_rm, "qualidade_ok", True),
                    "embalagem_ok": getattr(item_rm, "embalagem_ok", True),
                    "observacoes": getattr(item_rm, "observacoes", "")
                })
        else:
            # Cria um item padrão para exibir checkboxes mesmo sem RM
            itens_rm.append({
                "descricao": oc.get('descricao', ''),
                "quantidade": oc.get('quantidade', ''),
                "unidade_medida": oc.get('unidade_medida', ''),
                "chegado": False,
                "quantidade_ok": True,
                "qualidade_ok": True,
                "embalagem_ok": True,
                "observacoes": ""
            })

        itens_para_exibir.append({
            'numero_oc': numero_oc,
            'material': oc.get('descricao', ''),
            'quantidade': oc.get('quantidade', ''),
            'centro_custo': oc.get('centro_custo', ''),
            'previsao_entrega': data_formatada,
            'local_entrega': oc.get('local_entrega', ''),
            'alerta': alerta_item,
            'itens': itens_rm  # <-- Adiciona os itens da RM
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

    dados = request.get_json()

    # Marca como baixa e atualiza itens
    for oc in ordens_de_compra:
        if oc.get('numero_oc', '') == numero_oc:
            oc['baixa'] = True
            rm_relacionada = next((r for r in requisicoes if r.numero_oc == numero_oc), None)
            if rm_relacionada:
                for idx, item in enumerate(rm_relacionada.itens):
                    item.chegado = dados.get(f'chegado_{idx}', False)
                    item.quantidade_ok = dados.get(f'quantidade_ok_{idx}', 'não') == 'sim'
                    item.qualidade_ok = dados.get(f'qualidade_ok_{idx}', 'não') == 'sim'
                    item.embalagem_ok = dados.get(f'embalagem_ok_{idx}', 'não') == 'sim'
                    item.observacoes = dados.get(f'obs_{idx}', '')

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

# Frota da Empresa
@app.route('/frotas')
def frotas():
    return render_template("frotas.html", carros=carros, pagina_ativa="frotas")

agendamentos_viagens = []  # lista global para armazenar os agendamentos

# lista temporária para armazenar os carros
carros = []
agendamento_viagens = []

@app.route('/cadastrar_carro', methods=['POST'])
def cadastrar_carro():
    placa = request.form.get("placa")
    marca = request.form.get("marca")
    modelo = request.form.get("modelo")
    ano = request.form.get("ano")
    cor = request.form.get("cor")
    setor = request.form.get("setor")
    status = request.form.get("status")

    carro = {
        "placa": placa,
        "marca": marca,
        "modelo": modelo,
        "versao": request.form.get("versao"),
        "exercicio": request.form.get("exercicio"),
        "ano_fabricacao": request.form.get("ano_fabricacao"),
        "ano_modelo": request.form.get("ano_modelo"),
        "cor": cor,
        "chassi": request.form.get("chassi"),
        "link_doc": request.form.get("link_doc"),
        "locadora": request.form.get("locadora"),
        "num_contrato_locacao": request.form.get("num_contrato_locacao"),
        "contrato": request.form.get("contrato"),
        "empresa": request.form.get("empresa"),
        "rastreado": request.form.get("rastreado"),
        "ativo_desde": request.form.get("ativo_desde"),
        "status": status,
        "cartao_combustivel": request.form.get("cartao_combustivel"),
        "cartao_equipamento": request.form.get("cartao_equipamento")
    }


    carros.append(carro)  # salva na lista

    flash(f"Veículo {placa} cadastrado com sucesso!", "success")
    return redirect(url_for("frotas"))

@app.route('/editar_carro/<placa>', methods=['GET', 'POST'])
def editar_carro(placa):
    carro = next((c for c in carros if c["placa"] == placa), None)
    if not carro:
        flash("Carro não encontrado!", "danger")
        return redirect(url_for("frotas"))

    if request.method == 'POST':
        carro["marca"] = request.form.get("marca")
        carro["modelo"] = request.form.get("modelo")
        carro["ano"] = request.form.get("ano")
        carro["cor"] = request.form.get("cor")
        carro["setor"] = request.form.get("setor")
        carro["status"] = request.form.get("status")
        flash("Carro atualizado com sucesso!", "success")
        return redirect(url_for("frotas"))

    return render_template("editar_carro.html", carro=carro)


@app.route('/excluir_carro/<placa>', methods=['POST'])
def excluir_carro(placa):
    global carros
    carros = [c for c in carros if c["placa"] != placa]
    flash(f"Veículo {placa} removido com sucesso!", "success")
    return redirect(url_for("frotas"))


@app.route("/agendamento_viagens", methods=["GET", "POST"])
def agendamento_viagens():
    global agendamentos_viagens
    if request.method == "POST":
        # Pega os dados do formulário
        motorista = request.form.get("motorista")
        veiculo = request.form.get("veiculo")
        trechos = request.form.getlist("trecho[]")           # Lista de trechos
        datas_viagem = request.form.getlist("data_viagem[]") # Lista de datas
        horas_saida = request.form.getlist("hora_saida[]")   # Lista de horas
        observacoes = request.form.getlist("observacoes[]")  # Lista de observações
        passageiros = request.form.getlist("passageiro[]")   # Lista de passageiros
        empresa = request.form.get("empresa")
        prioridade = request.form.get("prioridade")
        email = request.form.get("email")
        status_viagem = "AGUARDANDO APROVAÇÃO"

        # Cria o agendamento
        agendamento = {
            "id": len(agendamentos_viagens) + 1,  # Número sequencial automático
            "motorista": motorista,
            "veiculo": veiculo,
            "trechos": trechos,
            "datas_viagem": datas_viagem,
            "horas_saida": horas_saida,
            "observacoes": observacoes,
            "passageiros": passageiros,
            "empresa": empresa,
            "prioridade": prioridade,
            "email": email,
            "status_viagem": status_viagem
        }
        agendamentos_viagens.append(agendamento)
        flash(f"Agendamento {agendamento['id']} criado com sucesso!")
        return redirect(url_for("agendamento_viagens"))

    # GET
    proximo_id = len(agendamentos_viagens) + 1  # Número sequencial
    return render_template("agendamento_viagens.html",
                           carros=carros,
                           status_viagem=["AGUARDANDO", "EM ANDAMENTO", "CONCLUÍDA", "CANCELADA"],
                           proximo_rm=f"AV-{proximo_id}")  # Passa para o template


@app.route("/controle_frota", methods=["GET", "POST"])
def controle_frota():
    if not session.get("logado"):
        return redirect(url_for("login"))

    if request.method == "POST":
        agendamento_id = request.form.get("agendamento_id")
        agendamento = next((a for a in agendamentos_viagens if str(a['id']) == agendamento_id), None)
        if agendamento:
            agendamento['motorista'] = request.form.get("motorista", agendamento['motorista'])
            agendamento['veiculo'] = request.form.get("veiculo", agendamento['veiculo'])
            agendamento['data_viagem'] = request.form.get("data_viagem", agendamento['data_viagem'])
            agendamento['status'] = request.form.get("status", agendamento['status'])
            agendamento['observacoes'] = request.form.get("observacoes", agendamento['observacoes'])
        flash(f"Agendamento {agendamento_id} atualizado com sucesso!")
        return redirect(url_for("controle_frota"))

    # Status possíveis da viagem
    status_viagem = ["AGUARDANDO", "EM ANDAMENTO", "CONCLUÍDA", "CANCELADA"]

    return render_template(
        "controle_frota.html",
        agendamentos=agendamentos_viagens,
        status_viagem=status_viagem
    )


from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import mm

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
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4

        # Cria PDF executivo
        doc = SimpleDocTemplate(buffer, pagesize=A4,
                                rightMargin=40, leftMargin=40,
                                topMargin=60, bottomMargin=40)

        story = []
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name="Titulo", fontSize=16, alignment=1,
                                spaceAfter=20, leading=20, fontName="Helvetica-Bold"))
        styles.add(ParagraphStyle(name="SubTitulo", fontSize=12,
                                spaceAfter=8, leading=14, fontName="Helvetica-Bold"))
        styles.add(ParagraphStyle(name="CustomNormal", fontSize=11, leading=14))

        # Cabeçalho executivo
        story.append(Paragraph(f"Pedido de Cotação - RM {rm_number}", styles["Titulo"]))
        story.append(Paragraph(f"<b>Requisitante:</b> {rm_obj.requisitante}", styles["CustomNormal"]))
        story.append(Paragraph(f"<b>Fornecedores Selecionados:</b> {', '.join(fornecedores_emails)}", styles["CustomNormal"]))
        story.append(Paragraph(f"<b>Prazo de Entrega Desejado:</b> {prazo_entrega}", styles["CustomNormal"]))
        story.append(Paragraph(f"<b>Condições Comerciais:</b> {condicoes}", styles["CustomNormal"]))
        story.append(Paragraph(f"<b>Observações:</b> {observacoes}", styles["CustomNormal"]))
        story.append(Spacer(1, 20))

        # Instruções executivas
        story.append(Paragraph("<b>Objetivo:</b> Obter propostas comerciais para aquisição dos itens listados, garantindo o melhor custo-benefício e condições de fornecimento para a empresa.", styles["CustomNormal"]))
        story.append(Spacer(1, 20))

        story.append(Paragraph("Instruções ao Fornecedor:", styles["SubTitulo"]))
        story.append(Paragraph("<ul>"
                            "<li>Enviar proposta detalhada com preços unitários e totais;</li>"
                            "<li>Informar condições de pagamento, prazo de entrega e validade da proposta;</li>"
                            "<li>Especificar garantias, frete e logística de entrega;</li>"
                            "<li>Responder até a data limite especificada.</li>"
                            "</ul>", styles["CustomNormal"]))
        story.append(Spacer(1, 20))

        # Tabela de itens
        story.append(Paragraph("Itens Solicitados:", styles["SubTitulo"]))
        tabela_dados = [["Qtd.", "Descrição", "Observações"]]
        for item in rm_obj.itens:
            tabela_dados.append([str(item.quantidade), item.descricao, item.observacoes or "—"])

        tabela = Table(tabela_dados, colWidths=[60, 300, 150])
        tabela.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#2563eb")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("ALIGN", (0,0), (-1,-1), "LEFT"),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("BOTTOMPADDING", (0,0), (-1,0), 10),
            ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ]))
        story.append(tabela)

        story.append(Spacer(1, 40))
        story.append(Paragraph("Atenciosamente,", styles["CustomNormal"]))
        story.append(Spacer(1, 30))
        story.append(Paragraph("<b>Departamento de Compras</b>", styles["CustomNormal"]))

        doc.build(story)
        buffer.seek(0)

        # Atualiza status
        rm_obj.atualizar_status("APENAS COTAÇÃO")

        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"Pedido_Cotacao_RM{rm_number}.pdf",
            mimetype="application/pdf"
        )

    # GET
    return render_template(
        "pedidos_compras.html",
        rm_aprovadas=rm_aprovadas,
        fornecedores=fornecedores,
        pedidos_cotacao=pedidos_cotacao,
        pagina_ativa="pedidos_compras",
        data_emissao=datetime.now()  # <-- Adiciona aqui também
    )

if __name__ == '__main__':
    # debug=True apenas para desenvolvimento
    app.run(host='0.0.0.0', port=5000, debug=True)
