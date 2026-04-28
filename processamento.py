import os
import json
import base64
import re
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY")
openai_model = os.getenv("OPENAI_MODEL_LINEARIZATION", "gpt-5.2-pro")
client = OpenAI(api_key=openai_api_key)


def enviar_imagem_para_openai(caminho_imagem, prompt):
    with open(caminho_imagem, "rb") as img_file:
        imagem_base64 = base64.b64encode(img_file.read()).decode()

    resposta = client.chat.completions.create(
        model=openai_model,
        messages=[
            {
                "role": "system",
                "content": "Você é um especialista em estruturação editorial acessível. Retorne a marcação JSON solicitada."
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{imagem_base64}",
                            "detail": "high"
                        }
                    }
                ]
            }
        ],
        temperature=0.2,
        max_tokens=4096
    )

    conteudo = resposta.choices[0].message.content

    # Salva o conteúdo cru para depuração
    with open("resposta_debug.txt", "a", encoding="utf-8") as f:
        f.write(f"\n\n### {os.path.basename(caminho_imagem)}\n{conteudo}")

    try:
        # Tenta extrair só o JSON do conteúdo recebido
        padrao_json = re.search(r'(\{.*\})', conteudo, re.DOTALL)
        if padrao_json:
            return json.loads(padrao_json.group(1))
        else:
            return {"erro": "Resposta não contém JSON válido", "resposta": conteudo}
    except Exception as e:
        return {"erro": str(e), "resposta": conteudo}


def processar_paginas(pasta_pngs, pasta_jsons, prompt):
    os.makedirs(pasta_jsons, exist_ok=True)

    arquivos = sorted([f for f in os.listdir(pasta_pngs) if f.endswith(".png")])
    for idx, arquivo in enumerate(arquivos, 1):
        nome_json = arquivo.replace(".png", ".json")
        json_path = os.path.join(pasta_jsons, nome_json)
        imagem_path = os.path.join(pasta_pngs, arquivo)

        if os.path.exists(json_path):
            print(f"⏭️ Já existe: {json_path}")
            continue

        print(f"🔎 Processando {arquivo} ({idx}/{len(arquivos)})...")
        resultado = enviar_imagem_para_openai(imagem_path, prompt)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(resultado, f, indent=2, ensure_ascii=False)

        print(f"✅ JSON salvo: {json_path}")
