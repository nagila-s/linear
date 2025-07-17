import os
import json
import streamlit as st
from dotenv import load_dotenv
from converter_pdf_para_png import converter_pdf_em_png
from processamento import processar_paginas

# ─── Carregar variáveis do ambiente ───

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)

senha_correta = os.getenv("APP_PASSWORD")

# 🔒 Proteção por senha
senha = st.text_input("🔒 Digite a senha para acessar", type="password")
if senha != senha_correta:
    st.warning("Acesso restrito. Digite a senha correta para continuar.")
    st.stop()

# Configurações da página

st.set_page_config(page_title="Teste Linear", layout="wide")
st.title("📘 Linear – Teste de Marcação de Páginas")

# Prompt padrão
prompt_padrao = """Leia o conteúdo da imagem e retorne em formato JSON estruturado.
Você é um editor preparando uma página para ser lida por uma pessoa com deficiência visual.
Essa pessoa precisa compreender as informações da página e a relação entre essas informações.
Seu trabalho é reconhecer, interpretar e marcar todos os elementos da página, identificando não apenas o formato visual, mas sua função pedagógica.
Cada bloco deve ser identificado com um tipo (ex: 'titulo', 'subtitulo', 'paragrafo', 'imagem', 'legenda', 'lista', 'quadro', 'nota'), manter negrito e itálico etc."""

# ──────────────────────────────
# Seção 1 – Conversão de PDF em imagens
# ──────────────────────────────
st.header("1️⃣ Converter PDF para Imagens")

pdf_file = st.file_uploader("📎 Envie o PDF para conversão", type="pdf", key="upload_pdf")

if pdf_file and st.button("▶️ Converter PDF para PNG"):
    nome_base = pdf_file.name.replace(".pdf", "")
    pasta_saida = f"./{nome_base}_imagens"
    os.makedirs(pasta_saida, exist_ok=True)

    st.info("⏳ Convertendo PDF para imagens...")
    converter_pdf_em_png(pdf_file.read(), pasta_saida, nome_base)
    st.success(f"✅ Imagens salvas em: `{pasta_saida}`")

# ──────────────────────────────
# Seção 2 – Processar imagens em JSON
# ──────────────────────────────
st.header("2️⃣ Processar Imagens com Linear")

pasta_imagens = st.text_input("📂 Caminho da pasta com imagens", "./nome_do_livro_imagens")
prompt_usuario = st.text_area("✏️ Prompt personalizado", prompt_padrao, height=250)

if st.button("🚀 Processar Imagens"):
    if not os.path.exists(pasta_imagens):
        st.error("❌ Pasta de imagens não encontrada.")
    else:
        pasta_jsons = pasta_imagens.rstrip("/\\") + "_json"
        st.info("⏳ Processando imagens...")
        processar_paginas(pasta_imagens, pasta_jsons, prompt_usuario)
        st.success(f"✅ JSONs gerados em: `{pasta_jsons}`")

        # Opção para baixar todos os JSONs combinados (apenas leitura)
        json_completo = {}
        for arquivo in sorted(os.listdir(pasta_jsons)):
            if arquivo.endswith(".json"):
                with open(os.path.join(pasta_jsons, arquivo), "r", encoding="utf-8") as f:
                    json_completo[arquivo] = json.load(f)

        st.download_button("⬇️ Baixar todos os JSONs combinados", json.dumps(json_completo, indent=2, ensure_ascii=False), file_name="resultados_completos.json")
