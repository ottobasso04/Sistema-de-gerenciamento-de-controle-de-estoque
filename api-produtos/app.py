import os
import time
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# ─── Configuração do Banco ────────────────────────────────────────────────────
MYSQL_HOST     = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT     = os.getenv("MYSQL_PORT", "3306")
MYSQL_DB       = os.getenv("MYSQL_DB", "estoque")
MYSQL_USER     = os.getenv("MYSQL_USER", "admin")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "senha123")

app.config["SQLALCHEMY_DATABASE_URI"] = (
    f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}"
    f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ─── Modelo ───────────────────────────────────────────────────────────────────
class Produto(db.Model):
    __tablename__ = "produtos"

    id        = db.Column(db.Integer, primary_key=True, autoincrement=True)
    nome      = db.Column(db.String(120), nullable=False)
    descricao = db.Column(db.String(300), nullable=True)
    preco     = db.Column(db.Float, nullable=False)
    categoria = db.Column(db.String(80), nullable=True)
    ativo     = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            "id":        self.id,
            "nome":      self.nome,
            "descricao": self.descricao,
            "preco":     self.preco,
            "categoria": self.categoria,
            "ativo":     self.ativo,
        }

# ─── Inicialização com retry ──────────────────────────────────────────────────
def init_db():
    for tentativa in range(10):
        try:
            with app.app_context():
                db.create_all()
            print("Banco de dados inicializado com sucesso.")
            return
        except Exception as e:
            print(f"Tentativa {tentativa + 1}/10 — aguardando MySQL... ({e})")
            time.sleep(4)
    raise RuntimeError("Não foi possível conectar ao MySQL após 10 tentativas.")

# ─── Rotas ────────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "servico": "api-produtos"}), 200

@app.route("/produtos", methods=["POST"])
def criar_produto():
    data = request.get_json()
    if not data or not data.get("nome") or not data.get("preco"):
        return jsonify({"erro": "Campos 'nome' e 'preco' são obrigatórios"}), 400

    produto = Produto(
        nome      = data["nome"],
        descricao = data.get("descricao"),
        preco     = data["preco"],
        categoria = data.get("categoria"),
        ativo     = data.get("ativo", True),
    )
    db.session.add(produto)
    db.session.commit()
    return jsonify(produto.to_dict()), 201

@app.route("/produtos", methods=["GET"])
def listar_produtos():
    categoria = request.args.get("categoria")
    query = Produto.query
    if categoria:
        query = query.filter_by(categoria=categoria)
    return jsonify([p.to_dict() for p in query.all()]), 200

@app.route("/produtos/<int:produto_id>", methods=["GET"])
def buscar_produto(produto_id):
    produto = Produto.query.get(produto_id)
    if not produto:
        return jsonify({"erro": "Produto não encontrado"}), 404
    return jsonify(produto.to_dict()), 200

@app.route("/produtos/<int:produto_id>", methods=["PUT"])
def atualizar_produto(produto_id):
    produto = Produto.query.get(produto_id)
    if not produto:
        return jsonify({"erro": "Produto não encontrado"}), 404

    data = request.get_json()
    produto.nome      = data.get("nome",      produto.nome)
    produto.descricao = data.get("descricao", produto.descricao)
    produto.preco     = data.get("preco",     produto.preco)
    produto.categoria = data.get("categoria", produto.categoria)
    produto.ativo     = data.get("ativo",     produto.ativo)

    db.session.commit()
    return jsonify(produto.to_dict()), 200

@app.route("/produtos/<int:produto_id>", methods=["DELETE"])
def remover_produto(produto_id):
    produto = Produto.query.get(produto_id)
    if not produto:
        return jsonify({"erro": "Produto não encontrado"}), 404

    db.session.delete(produto)
    db.session.commit()
    return jsonify({"mensagem": f"Produto {produto_id} removido com sucesso"}), 200

# ─── Iniciar ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5001, debug=False)