from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = '04031998'

UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

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
        senha = request.form.get("senha")
        if senha == "040398":
            session["logado"] = True
            return redirect(url_for("controle"))
        else:
            return render_template("login.html", erro="Senha incorreta.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("logado", None)
    return redirect(url_for("login"))

@app.route("/novo_pedido", methods=["GET", "POST"])
def novo_pedido():
    if request.method == "POST":
        rm = request.form.get("rm")
        if not rm or not rm.isdigit():
            flash("Número RM inválido")
            return redirect(url_for("novo_pedido"))
        id_req = int(rm)

        # Evita duplicação de RM
        if any(r.id_req == id_req for r in requisicoes):
            flash("RM já existe. Por favor, atualize a página para obter o próximo número.")
            return redirect(url_for("novo_pedido"))

        requisitante = request.form.get("requisitante")
        descricoes = request.form.getlist("descricao[]")
        qtds = request.form.getlist("qtd[]")
        anexos = request.files.getlist("anexo[]")

        itens = []
        for i in range(len(descricoes)):
            desc = descricoes[i]
            qtd = int(qtds[i]) if qtds[i].isdigit() else 1
            arquivo = anexos[i] if i < len(anexos) else None
            filename = None
            if arquivo and arquivo.filename:
                filename = f"rm{id_req}_item{i+1}_" + arquivo.filename
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                arquivo.save(filepath)
            itens.append(Item(desc, qtd, filename))

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
        else:
            # Opcional: assign não listados para "SOLICITAÇÃO APROVADA" ou ignore
            pass

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

if __name__ == "__main__":
    app.run(debug=True)
