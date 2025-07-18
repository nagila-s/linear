import os
import json
import streamlit as st
from processamento import enviar_imagem_para_openai
from dotenv import load_dotenv

load_dotenv()

# Proteção com senha
import streamlit as st
senha_correta = os.getenv("APP_PASSWORD")

senha = st.text_input("🔒 Digite a senha para acessar", type="password")
if senha != senha_correta:
    st.warning("Acesso restrito. Digite a senha correta para continuar.")
    st.stop()

# Configuração inicial
st.set_page_config(page_title="Linear IA", layout="wide")
st.title("📘 Linear – Pré-processamento de pdfs")

# Opções disponíveis
opcoes_livros = {
    "Literário simples": "litTEX",
    "Literário ilustrado": "litILUS",
    "Didático simples": "didSIMP",
    "Didático complexo": "didCOMP"
}

livro_escolhido_label = st.selectbox("📚 Escolha um livro para testar:", list(opcoes_livros.keys()))
livro_id = opcoes_livros[livro_escolhido_label]
pasta_imagens = os.path.join("livros", livro_id, "imagens")

if not os.path.exists(pasta_imagens):
    st.error(f"A pasta `{pasta_imagens}` não foi encontrada. Verifique os diretórios locais.")
    st.stop()

# Descobrir páginas disponíveis
arquivos_png = sorted([f for f in os.listdir(pasta_imagens) if f.endswith(".png")])
total_paginas = len(arquivos_png)

st.info(f"O livro contém {total_paginas} páginas.")

intervalo = st.slider("📖 Selecione intervalo de páginas:", min_value=1, max_value=total_paginas, value=(1, min(5, total_paginas)))

# Prompt padrão
prompt_padrao = """Leia o conteúdo da imagem e retorne em formato JSON estruturado.
Você é um editor preparando uma página para ser lida por uma pessoa com deficiência visual.
Essa pessoa precisa compreender as informações da página e a relação entre essas informações.
Seu trabalho é reconhecer, interpretar e marcar todos os elementos da página, identificando não apenas o formato visual, mas sua função pedagógica.
Cada bloco deve ser identificado com um tipo (ex: 'titulo', 'subtitulo', 'paragrafo', 'imagem', 'legenda', 'lista', 'quadro', 'nota'), manter negrito e itálico etc."""

prompt_usuario = st.text_area("✏️ Prompt personalizado", prompt_padrao, height=250)

# Processamento
if st.button("🚀 Processar intervalo selecionado"):
    st.info("Enviando imagens para a OpenAI. Isso pode levar alguns segundos...")

    resultados = {}
    for i in range(intervalo[0], intervalo[1]+1):
        nome_arquivo = f"{livro_id}_p{i:03}.png"
        caminho = os.path.join(pasta_imagens, nome_arquivo)

        if not os.path.exists(caminho):
            st.warning(f"⚠️ Página {i} ({nome_arquivo}) não encontrada. Pulando.")
            continue

        st.write(f"📄 Processando página {i}...")
        resultado = enviar_imagem_para_openai(caminho, prompt_usuario)
        resultados[nome_arquivo] = resultado

    st.success("✅ Processamento concluído.")
    
    # Salvar arquivo temporariamente
    arquivo_json = f"{livro_id}_{intervalo[0]:03}_{intervalo[1]:03}_resultado.json"
    with open(arquivo_json, "w", encoding="utf-8") as f:
        json.dump(resultados, f, indent=2, ensure_ascii=False)

    st.download_button("⬇️ Baixar resultado", json.dumps(resultados, indent=2, ensure_ascii=False), file_name=arquivo_json)
