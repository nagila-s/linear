from pdf2image import convert_from_bytes
import os

def converter_pdf_em_png(conteudo_pdf, pasta_saida, prefixo_arquivo, dpi=300):
    os.makedirs(pasta_saida, exist_ok=True)
    imagens = convert_from_bytes(conteudo_pdf, dpi=dpi, fmt="png", grayscale=True)

    for i, img in enumerate(imagens):
        nome_arquivo = f"{prefixo_arquivo}_p{i+1:03}.png"
        caminho = os.path.join(pasta_saida, nome_arquivo)
        img.save(caminho, "PNG")
    
    print(f"✅ PDF convertido para {len(imagens)} PNGs em {pasta_saida}")


