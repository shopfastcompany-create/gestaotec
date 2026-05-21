import os

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from datetime import datetime

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

app = Flask(__name__)
app.secret_key = "gestaotec_secret_key"


# =========================
# BANCO
# =========================
def conectar():
    return sqlite3.connect("gestaotec.db")


def usuario_logado():
    return "usuario" in session


def resumo_gestao():
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM clientes")
    total_clientes = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM projetos")
    total_projetos = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM tarefas")
    total_tarefas = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(valor) FROM financeiro WHERE tipo='Entrada'")
    entradas = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM financeiro WHERE tipo=?", ("Sa\u00edda",))
    saidas = cursor.fetchone()[0] or 0

    cursor.execute("SELECT nome, cliente, status FROM projetos ORDER BY id DESC LIMIT 5")
    projetos = cursor.fetchall()

    cursor.execute("SELECT titulo, responsavel, status, prazo FROM tarefas ORDER BY id DESC LIMIT 5")
    tarefas = cursor.fetchall()

    conn.close()

    saldo = entradas - saidas
    return {
        "total_clientes": total_clientes,
        "total_projetos": total_projetos,
        "total_tarefas": total_tarefas,
        "entradas": entradas,
        "saidas": saidas,
        "saldo": saldo,
        "projetos": projetos,
        "tarefas": tarefas,
    }


def resposta_local(pergunta, contexto):
    pergunta_baixa = pergunta.lower()

    if "saldo" in pergunta_baixa or "financeiro" in pergunta_baixa:
        return (
            f"O saldo atual e de R$ {contexto['saldo']:.2f}. "
            f"As entradas somam R$ {contexto['entradas']:.2f} e as saidas somam R$ {contexto['saidas']:.2f}."
        )

    if "projeto" in pergunta_baixa:
        projetos = contexto["projetos"]
        if not projetos:
            return "Ainda nao ha projetos cadastrados."
        itens = "; ".join([f"{nome} para {cliente} ({status})" for nome, cliente, status in projetos])
        return f"Voce tem {contexto['total_projetos']} projetos cadastrados. Mais recentes: {itens}."

    if "tarefa" in pergunta_baixa:
        tarefas = contexto["tarefas"]
        if not tarefas:
            return "Ainda nao ha tarefas cadastradas."
        itens = "; ".join([f"{titulo} - {status}" for titulo, _, status, _ in tarefas])
        return f"Voce tem {contexto['total_tarefas']} tarefas cadastradas. Mais recentes: {itens}."

    return (
        "Posso ajudar a analisar clientes, financeiro, projetos e tarefas. "
        f"No momento ha {contexto['total_clientes']} clientes, {contexto['total_projetos']} projetos "
        f"e {contexto['total_tarefas']} tarefas na base."
    )


def gerar_resposta_ia(pergunta):
    contexto = resumo_gestao()
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key or OpenAI is None:
        return resposta_local(pergunta, contexto), False

    cliente = OpenAI(api_key=api_key)
    prompt_contexto = f"""
Usuario: {session.get('usuario')}
Clientes cadastrados: {contexto['total_clientes']}
Projetos cadastrados: {contexto['total_projetos']}
Tarefas cadastradas: {contexto['total_tarefas']}
Entradas: R$ {contexto['entradas']:.2f}
Saidas: R$ {contexto['saidas']:.2f}
Saldo: R$ {contexto['saldo']:.2f}
Projetos recentes: {contexto['projetos']}
Tarefas recentes: {contexto['tarefas']}
"""

    resposta = cliente.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5"),
        instructions=(
            "Voce e o assistente de gestao do sistema GestaoTec+. "
            "Responda em portugues do Brasil, com objetividade, usando somente os dados fornecidos "
            "quando falar da empresa. Se faltar dado, diga o que precisa ser cadastrado."
        ),
        input=[
            {"role": "developer", "content": prompt_contexto},
            {"role": "user", "content": pergunta},
        ],
    )

    return resposta.output_text.strip(), True


def criar_banco():
    conn = conectar()
    cursor = conn.cursor()

    # TABELAS
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            email TEXT,
            senha TEXT,
            perfil TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            empresa TEXT,
            telefone TEXT,
            email TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS financeiro (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT,
            tipo TEXT,
            valor REAL,
            data TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS projetos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            cliente TEXT,
            status TEXT,
            data_inicio TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tarefas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT,
            responsavel TEXT,
            status TEXT,
            prazo TEXT
        )
    """)

    # USUARIO PADRÃO
    cursor.execute("""
        INSERT OR IGNORE INTO usuarios (id, nome, email, senha, perfil)
        VALUES (1, 'Administrador', 'admin@gestaotec.com', '123456', 'admin')
    """)

    # DADOS FICTÍCIOS
    cursor.execute("SELECT COUNT(*) FROM clientes")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("""
            INSERT INTO clientes (nome, empresa, telefone, email)
            VALUES (?, ?, ?, ?)
        """, [
            ("Carlos Mendes", "Mendes Soluções", "(11)98888-1111", "carlos@mendes.com"),
            ("Fernanda Lima", "Lima Consultoria", "(11)97777-2222", "fernanda@lima.com"),
            ("Rafael Souza", "Souza Tech", "(11)96666-3333", "rafael@souzatech.com"),
            ("Juliana Rocha", "Rocha Digital", "(11)95555-4444", "juliana@rocha.com")
        ])

    cursor.execute("SELECT COUNT(*) FROM financeiro")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("""
            INSERT INTO financeiro (descricao, tipo, valor, data)
            VALUES (?, ?, ?, ?)
        """, [
            ("Projeto ERP", "Entrada", 5000, "03/05/2026"),
            ("Consultoria TI", "Entrada", 3000, "03/05/2026"),
            ("Servidor cloud", "Saída", 200, "03/05/2026"),
            ("Licenças software", "Saída", 150, "03/05/2026")
        ])

    cursor.execute("SELECT COUNT(*) FROM projetos")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("""
            INSERT INTO projetos (nome, cliente, status, data_inicio)
            VALUES (?, ?, ?, ?)
        """, [
            ("Sistema ERP", "Mendes Soluções", "Em andamento", "01/05/2026"),
            ("Site institucional", "Lima Consultoria", "Concluído", "20/04/2026"),
            ("Dashboard BI", "Souza Tech", "Em andamento", "25/04/2026"),
            ("App mobile", "Rocha Digital", "Pausado", "15/04/2026")
        ])

    cursor.execute("SELECT COUNT(*) FROM tarefas")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("""
            INSERT INTO tarefas (titulo, responsavel, status, prazo)
            VALUES (?, ?, ?, ?)
        """, [
            ("Criar login", "Marco", "Concluída", "2026-05-01"),
            ("Banco de dados", "Equipe", "Concluída", "2026-05-02"),
            ("Dashboard", "Marco", "Em andamento", "2026-05-04"),
            ("Relatórios", "Equipe", "Pendente", "2026-05-06")
        ])

    conn.commit()
    conn.close()


criar_banco()


# =========================
# LOGIN
# =========================
@app.route("/", methods=["GET", "POST"])
def login():
    erro = None

    if request.method == "POST":
        email = request.form["email"]
        senha = request.form["senha"]

        conn = conectar()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM usuarios WHERE email=? AND senha=?",
            (email, senha)
        )
        usuario = cursor.fetchone()
        conn.close()

        if usuario:
            session["usuario"] = usuario[1]
            return redirect("/dashboard")
        else:
            erro = "Login inválido"

    return render_template("login.html", erro=erro)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# =========================
# DASHBOARD
# =========================
@app.route("/dashboard")
def dashboard():
    if not usuario_logado():
        return redirect("/")

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM clientes")
    clientes = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM projetos")
    projetos = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM tarefas")
    tarefas = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(valor) FROM financeiro WHERE tipo='Entrada'")
    entradas = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(valor) FROM financeiro WHERE tipo=?", ("Sa\u00edda",))
    saidas = cursor.fetchone()[0] or 0

    saldo = entradas - saidas

    conn.close()

    return render_template(
        "dashboard.html",
        total_clientes=clientes,
        total_projetos=projetos,
        total_tarefas=tarefas,
        entradas=entradas,
        saidas=saidas,
        saldo=saldo
    )


@app.route("/ia")
def ia():
    if not usuario_logado():
        return redirect("/")

    modo_ia = bool(os.getenv("OPENAI_API_KEY") and OpenAI is not None)
    return render_template("ia.html", modo_ia=modo_ia)


@app.route("/api/ia", methods=["POST"])
def api_ia():
    if not usuario_logado():
        return jsonify({"erro": "Usuario nao autenticado"}), 401

    dados = request.get_json(silent=True) or {}
    pergunta = (dados.get("mensagem") or "").strip()

    if not pergunta:
        return jsonify({"erro": "Digite uma mensagem para a IA."}), 400

    try:
        resposta, usando_openai = gerar_resposta_ia(pergunta)
        return jsonify({"resposta": resposta, "usando_openai": usando_openai})
    except Exception as erro:
        return jsonify({
            "erro": "Nao foi possivel consultar a IA agora.",
            "detalhe": str(erro)
        }), 500


# ROTAS
@app.route("/clientes", methods=["GET", "POST"])
def clientes():
    if not usuario_logado():
        return redirect("/")

    conn = conectar()
    cursor = conn.cursor()

    if request.method == "POST":
        cursor.execute("""
            INSERT INTO clientes (nome, empresa, telefone, email)
            VALUES (?, ?, ?, ?)
        """, (
            request.form["nome"],
            request.form["empresa"],
            request.form["telefone"],
            request.form["email"]
        ))
        conn.commit()

    cursor.execute("SELECT * FROM clientes")
    dados = cursor.fetchall()
    conn.close()

    return render_template("clientes.html", clientes=dados)


@app.route("/financeiro", methods=["GET", "POST"])
def financeiro():
    if not usuario_logado():
        return redirect("/")

    conn = conectar()
    cursor = conn.cursor()

    if request.method == "POST":
        cursor.execute("""
            INSERT INTO financeiro (descricao, tipo, valor, data)
            VALUES (?, ?, ?, ?)
        """, (
            request.form["descricao"],
            request.form["tipo"],
            request.form["valor"],
            datetime.now().strftime("%d/%m/%Y")
        ))
        conn.commit()

    cursor.execute("SELECT * FROM financeiro")
    dados = cursor.fetchall()
    conn.close()

    return render_template("financeiro.html", lancamentos=dados)


@app.route("/projetos", methods=["GET", "POST"])
def projetos():
    if not usuario_logado():
        return redirect("/")

    conn = conectar()
    cursor = conn.cursor()

    if request.method == "POST":
        cursor.execute("""
            INSERT INTO projetos (nome, cliente, status, data_inicio)
            VALUES (?, ?, ?, ?)
        """, (
            request.form["nome"],
            request.form["cliente"],
            request.form["status"],
            datetime.now().strftime("%d/%m/%Y")
        ))
        conn.commit()

    cursor.execute("SELECT * FROM projetos")
    dados = cursor.fetchall()
    conn.close()

    return render_template("projetos.html", projetos=dados)


@app.route("/tarefas", methods=["GET", "POST"])
def tarefas():
    if not usuario_logado():
        return redirect("/")

    conn = conectar()
    cursor = conn.cursor()

    if request.method == "POST":
        cursor.execute("""
            INSERT INTO tarefas (titulo, responsavel, status, prazo)
            VALUES (?, ?, ?, ?)
        """, (
            request.form["titulo"],
            request.form["responsavel"],
            request.form["status"],
            request.form["prazo"]
        ))
        conn.commit()

    cursor.execute("SELECT * FROM tarefas")
    dados = cursor.fetchall()
    conn.close()

    return render_template("tarefas.html", tarefas=dados)


if __name__ == "__main__":
    app.run(debug=True)
