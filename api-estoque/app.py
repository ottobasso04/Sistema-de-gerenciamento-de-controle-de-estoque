import os
import time
from datetime import datetime
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from pymongo import MongoClient
import requests as http

app = Flask(__name__)

# ─── Configuração MySQL ───────────────────────────────────────────────────────
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

# ─── Configuração MongoDB ─────────────────────────────────────────────────────
MONGO_HOST       = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT       = int(os.getenv("MONGO_PORT", "27017"))
MONGO_DB         = os.getenv("MONGO_DB", "estoque")
API_PRODUTOS_URL = os.getenv("API_PRODUTOS_URL", "http://localhost:5001")

mongo_client = MongoClient(MONGO_HOST, MONGO_PORT)
mongo_db     = mongo_client[MONGO_DB]
logs_col     = mongo_db["logs_estoque"]

# ─── Modelo ───────────────────────────────────────────────────────────────────
class Estoque(db.Model):
    __tablename__ = "estoque"

    id          = db.Column(db.Integer, primary_key=True, autoincrement=True)
    produto_id  = db.Column(db.Integer, nullable=False, unique=True)
    quantidade  = db.Column(db.Integer, nullable=False, default=0)
    localizacao = db.Column(db.String(80), nullable=True)
    atualizado  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id":          self.id,
            "produto_id":  self.produto_id,
            "quantidade":  self.quantidade,
            "localizacao": self.localizacao,
            "atualizado":  self.atualizado.isoformat() if self.atualizado else None,
        }

# ─── Helpers ──────────────────────────────────────────────────────────────────
def registrar_log(acao, produto_id, detalhes=None):
    logs_col.insert_one({
        "acao":       acao,
        "produto_id": produto_id,
        "detalhes":   detalhes or {},
        "timestamp":  datetime.utcnow().isoformat(),
    })

def produto_existe(produto_id):
    try:
        r = http.get(f"{API_PRODUTOS_URL}/produtos/{produto_id}", timeout=3)
        return r.status_code == 200
    except Exception:
        return False

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
    return jsonify({"status": "ok", "servico": "api-estoque"}), 200

@app.route("/estoque", methods=["POST"])
def criar_estoque():
    data = request.get_json()
    produto_id = data.get("produto_id")
    if not produto_id:
        return jsonify({"erro": "Campo 'produto_id' é obrigatório"}), 400

    if not produto_existe(produto_id):
        return jsonify({"erro": f"Produto {produto_id} não encontrado na api-produtos"}), 404

    existente = Estoque.query.filter_by(produto_id=produto_id).first()
    if existente:
        return jsonify({"erro": "Estoque para esse produto já existe"}), 409

    item = Estoque(
        produto_id  = produto_id,
        quantidade  = data.get("quantidade", 0),
        localizacao = data.get("localizacao"),
        atualizado  = datetime.utcnow(),
    )
    db.session.add(item)
    db.session.commit()

    registrar_log("criacao_estoque", produto_id, {"quantidade_inicial": item.quantidade})
    return jsonify(item.to_dict()), 201

@app.route("/estoque", methods=["GET"])
def listar_estoque():
    return jsonify([i.to_dict() for i in Estoque.query.all()]), 200

@app.route("/estoque/<int:produto_id>", methods=["GET"])
def buscar_estoque(produto_id):
    item = Estoque.query.filter_by(produto_id=produto_id).first()
    if not item:
        return jsonify({"erro": "Estoque não encontrado para esse produto"}), 404
    return jsonify(item.to_dict()), 200

@app.route("/estoque/<int:produto_id>", methods=["PUT"])
def atualizar_estoque(produto_id):
    item = Estoque.query.filter_by(produto_id=produto_id).first()
    if not item:
        return jsonify({"erro": "Estoque não encontrado para esse produto"}), 404

    data = request.get_json()
    quantidade_anterior = item.quantidade
    item.quantidade  = data.get("quantidade",  item.quantidade)
    item.localizacao = data.get("localizacao", item.localizacao)
    item.atualizado  = datetime.utcnow()
    db.session.commit()

    registrar_log("atualizacao_estoque", produto_id, {
        "quantidade_anterior": quantidade_anterior,
        "quantidade_nova":     item.quantidade,
    })
    return jsonify(item.to_dict()), 200

@app.route("/estoque/<int:produto_id>", methods=["DELETE"])
def remover_estoque(produto_id):
    item = Estoque.query.filter_by(produto_id=produto_id).first()
    if not item:
        return jsonify({"erro": "Estoque não encontrado para esse produto"}), 404

    db.session.delete(item)
    db.session.commit()
    registrar_log("remocao_estoque", produto_id)
    return jsonify({"mensagem": f"Estoque do produto {produto_id} removido"}), 200

@app.route("/estoque/logs", methods=["GET"])
def listar_logs():
    logs = list(logs_col.find({}, {"_id": 0}).sort("timestamp", -1).limit(50))
    return jsonify(logs), 200

# ─── Iniciar ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5002, debug=False)