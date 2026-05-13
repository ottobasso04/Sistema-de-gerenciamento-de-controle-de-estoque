import os
from datetime import datetime
from bson import ObjectId
from flask import Flask, jsonify, request
from pymongo import MongoClient
import requests as http

app = Flask(__name__)

# ─── Configuração MongoDB ─────────────────────────────────────────────────────
MONGO_HOST       = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT       = int(os.getenv("MONGO_PORT", "27017"))
MONGO_DB         = os.getenv("MONGO_DB", "estoque")
API_ESTOQUE_URL  = os.getenv("API_ESTOQUE_URL",  "http://localhost:5002")
API_PRODUTOS_URL = os.getenv("API_PRODUTOS_URL", "http://localhost:5001")

mongo_client = MongoClient(MONGO_HOST, MONGO_PORT)
mongo_db     = mongo_client[MONGO_DB]
mov_col      = mongo_db["movimentacoes"]

# ─── Helpers ──────────────────────────────────────────────────────────────────
def serializar(doc):
    doc["_id"] = str(doc["_id"])
    return doc

def atualizar_quantidade(produto_id, delta):
    try:
        r = http.get(f"{API_ESTOQUE_URL}/estoque/{produto_id}", timeout=3)
        if r.status_code == 404:
            return False, "Produto não tem registro no estoque", None

        quantidade_atual = r.json()["quantidade"]
        quantidade_nova  = quantidade_atual + delta

        if quantidade_nova < 0:
            return False, f"Estoque insuficiente. Disponível: {quantidade_atual}", None

        patch = http.put(
            f"{API_ESTOQUE_URL}/estoque/{produto_id}",
            json={"quantidade": quantidade_nova},
            timeout=3,
        )
        if patch.status_code != 200:
            return False, "Erro ao atualizar estoque", None

        return True, "ok", quantidade_nova
    except Exception as e:
        return False, str(e), None

# ─── Rotas ────────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "servico": "api-movimentacoes"}), 200

@app.route("/movimentacoes", methods=["POST"])
def criar_movimentacao():
    data       = request.get_json()
    tipo       = data.get("tipo")
    produto_id = data.get("produto_id")
    quantidade = data.get("quantidade")

    if not all([tipo, produto_id, quantidade]):
        return jsonify({"erro": "Campos 'tipo', 'produto_id' e 'quantidade' são obrigatórios"}), 400
    if tipo not in ("entrada", "saida"):
        return jsonify({"erro": "Campo 'tipo' deve ser 'entrada' ou 'saida'"}), 400
    if quantidade <= 0:
        return jsonify({"erro": "Quantidade deve ser maior que zero"}), 400

    try:
        r = http.get(f"{API_PRODUTOS_URL}/produtos/{produto_id}", timeout=3)
        if r.status_code != 200:
            return jsonify({"erro": f"Produto {produto_id} não encontrado"}), 404
        produto = r.json()
    except Exception as e:
        return jsonify({"erro": f"Erro ao consultar api-produtos: {e}"}), 503

    delta = quantidade if tipo == "entrada" else -quantidade
    ok, msg, qtd_nova = atualizar_quantidade(produto_id, delta)
    if not ok:
        return jsonify({"erro": msg}), 422

    documento = {
        "tipo":               tipo,
        "produto_id":         produto_id,
        "produto_nome":       produto.get("nome"),
        "quantidade":         quantidade,
        "quantidade_estoque": qtd_nova,
        "responsavel":        data.get("responsavel", "sistema"),
        "data":               datetime.utcnow().isoformat(),
        "motivo":             data.get("motivo"),
    }

    if tipo == "entrada":
        documento["fornecedor"]  = data.get("fornecedor")
        documento["nota_fiscal"] = data.get("nota_fiscal")
    else:
        documento["cliente"]  = data.get("cliente")
        documento["destino"]  = data.get("destino")

    resultado = mov_col.insert_one(documento)
    documento["_id"] = str(resultado.inserted_id)
    return jsonify(documento), 201

@app.route("/movimentacoes", methods=["GET"])
def listar_movimentacoes():
    filtro     = {}
    tipo       = request.args.get("tipo")
    produto_id = request.args.get("produto_id")
    if tipo:
        filtro["tipo"] = tipo
    if produto_id:
        filtro["produto_id"] = int(produto_id)

    limite = int(request.args.get("limite", 50))
    movs   = list(mov_col.find(filtro).sort("data", -1).limit(limite))
    return jsonify([serializar(m) for m in movs]), 200

@app.route("/movimentacoes/<mov_id>", methods=["GET"])
def buscar_movimentacao(mov_id):
    try:
        mov = mov_col.find_one({"_id": ObjectId(mov_id)})
    except Exception:
        return jsonify({"erro": "ID inválido"}), 400
    if not mov:
        return jsonify({"erro": "Movimentação não encontrada"}), 404
    return jsonify(serializar(mov)), 200

@app.route("/movimentacoes/<mov_id>", methods=["PUT"])
def atualizar_movimentacao(mov_id):
    try:
        oid = ObjectId(mov_id)
    except Exception:
        return jsonify({"erro": "ID inválido"}), 400

    mov = mov_col.find_one({"_id": oid})
    if not mov:
        return jsonify({"erro": "Movimentação não encontrada"}), 404

    data = request.get_json()
    campos_permitidos = ["responsavel", "motivo", "fornecedor", "nota_fiscal", "cliente", "destino"]
    update = {k: v for k, v in data.items() if k in campos_permitidos}

    if not update:
        return jsonify({"erro": "Nenhum campo editável informado"}), 400

    mov_col.update_one({"_id": oid}, {"$set": update})
    return jsonify(serializar(mov_col.find_one({"_id": oid}))), 200

@app.route("/movimentacoes/<mov_id>", methods=["DELETE"])
def remover_movimentacao(mov_id):
    try:
        oid = ObjectId(mov_id)
    except Exception:
        return jsonify({"erro": "ID inválido"}), 400

    resultado = mov_col.delete_one({"_id": oid})
    if resultado.deleted_count == 0:
        return jsonify({"erro": "Movimentação não encontrada"}), 404
    return jsonify({"mensagem": f"Movimentação {mov_id} removida"}), 200

@app.route("/movimentacoes/resumo/<int:produto_id>", methods=["GET"])
def resumo_produto(produto_id):
    pipeline = [
        {"$match": {"produto_id": produto_id}},
        {"$group": {
            "_id":            "$tipo",
            "total_movs":     {"$sum": 1},
            "total_unidades": {"$sum": "$quantidade"},
        }},
    ]
    return jsonify(list(mov_col.aggregate(pipeline))), 200

# ─── Iniciar ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=False)