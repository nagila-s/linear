# Extrator de figuras novo no Linear: avaliação e plano

Data: 2026-11-03. Extrator avaliado: `~/Documents/extrator-figuras` (`pdf_figure_extractor`, árvore de trabalho com cerca de 900 linhas ainda não commitadas).

## 1. Como o Linear faz hoje

Código em `src/pipeline/steps/pdf_images.py`, chamado por `src/worker/pipeline/stages/extract_images.py:224`.

- Usa só PyMuPDF. Pega `get_image_info` e renderiza o bbox de cada imagem com `get_pixmap(clip=…)` em 120 dpi na AWS.
- Os vetores estão desligados: `include_vector_clusters=False`. Mapas e gráficos vetoriais nunca viram figura.
- `_is_near_full_page_crop` descarta qualquer imagem com mais de 32% da página ou mais de 82% de um lado. Fotos grandes somem.
- Toda página sem figura recebe a página inteira como `fig1` (`render_fallback_dpi=dpi`).
- A ordem de `fig1..N` é a ordem interna do PDF, não a de leitura. A IA numera as figuras na ordem visual, e `_resolve_targets` (`describe.py:161`) casa as duas por chave ou por posição. Quando a ordem diverge, a Dorina descreve a figura errada.
- Não guarda bbox, legenda nem âncora.

Rodando nos mesmos livros:

| Livro | Páginas | Atual: recortes | Atual: página inteira como figura | Tempo atual | Novo: figuras | Tempo novo |
|---|---|---|---|---|---|---|
| Expedições da História 6 | 252 | 334 | 56 | 21 s | 352 | 121 s |
| MPU LP 5º ano | 316 | 217 | 204 | 49 s | 136 | 129 s |
| MPU Matemática 2º ano | 292 | 617 | 102 | 43 s | 334 | 218 s |

## 2. Avaliação do extrator novo

### Pontos fortes

- Ordem de leitura com detecção de duas colunas. Resolve o desalinhamento entre `figN` e a numeração da IA.
- Detecta mapas e diagramas vetoriais pelos paths e pelo clipping. Em História, um mapa da África saiu como uma figura só.
- Usa o retângulo visível (clip) da imagem, não o retângulo de posicionamento.
- Não descarta fotos grandes. Descarta fundo de página, cabeçalho, rodapé, tabela, pauta e caixa pedagógica.
- Entrega bbox, `source` e `confidence`, mais legenda e âncora para contexto.
- Robusto nos testes: 860 páginas reais sem nenhuma exceção. Mediana de 0,4 s por página, p95 de 2,8 s, máximo de 5,3 s, pico de 380 MB de RAM. A task da AWS tem 8 GB.
- Código modular, com contrato (`consumers.as_linear_figures`) já pensado para o Linear e 13 testes passando.

### Problemas encontrados

**P0: corrigir antes de integrar**

1. **Imagens fatiadas são descartadas antes de serem juntadas.** Em `extract.py:100-105`, `passes()` filtra cada imagem e só depois `_group_images` junta as fatias. Cada fatia sozinha é pequena demais e cai. Exemplo: LP 5º ano, p. 20, duas faixas de 170×46 e 170×26 pt rejeitadas por "lado mínimo" e "pequena demais". Correção: agrupar primeiro e filtrar depois.
2. **Recorte com fundo transparente (SMask) pega o texto de trás.** O bbox é o retângulo da imagem, não a parte opaca. No `eja curto.pdf`, p. 2, o PNG do celular inclui "EVOLUÇÃO DO APARELHO CELULAR" e metade do parágrafo. A Dorina vai ler esse texto. Correção: aparar o bbox pela área com alfa maior que zero do SMask.
3. **Ilustração grande com balões de fala é tratada como fundo.** `_is_backdrop` considera fundo qualquer imagem entre 40% e 85% da página com 3 ou mais linhas de texto por cima, e ainda a mascara da detecção visual. No Matemática 2º ano, p. 13 (menina com desenho e geoplano), saem zero figuras. Correção: exigir também conteúdo pobre (desvio padrão baixo ou poucas cores) para chamar de fundo, e não mascarar fundo na detecção visual.
4. **`_is_typeset_block` derruba imagem nativa.** O poema visual do LP 5º ano, p. 133, foi rejeitado como "bloco de texto". Para imagem nativa (XObject), isso deveria só baixar a confiança ou marcar, não excluir.
5. **O PNG sai do raster da página em 160 dpi.**
   - Uma figura pequena vira 100 a 200 px, pouco para a Dorina.
   - Se o Linear passar o próprio raster em `page_images`, que é **cinza**, a Dorina recebe a figura sem cor.
   - Correção: gerar o PNG com `page.get_pixmap(clip=crop, dpi=adaptativo)` em RGB, com lado maior entre cerca de 768 e 2048 px. O raster da página fica só para a detecção.
6. **Recorte vazio vira um PNG preto de 8×8** (`extract.py:508`). Deveria descartar a figura.

**P1: qualidade do contexto**

7. **A legenda depende de uma regex** (`Figura|Foto|Mapa|…`). Taxa de acerto: 13 de 352, 5 de 136 e 0 de 334. Livro brasileiro quase não usa "Figura N". Fica de fora, por exemplo, "MODELO DE APARELHO CELULAR DOS ANOS 1990." e "Visitantes observam exposição…". Correção: detectar legenda por posição e tipografia (bloco curto, adjacente, alinhado, fonte menor que o corpo) e separar o crédito em campo próprio: texto girado 90°, padrão "NOME/AGÊNCIA".
8. **A âncora pode ser a legenda de outra figura.** No História, p. 36, a âncora do mapa é a legenda da foto. A âncora precisa excluir legendas e créditos de qualquer figura da página. Hoje `column_gutter` é recalculado a cada figura; dá para calcular uma vez por página.

**P2: desempenho e operação**

9. `page.get_text("dict")` roda 4 vezes por página (em `load_text_blocks`, `running_text_lines`, `_text_spans` e `_painted_image_boxes`). Basta extrair uma vez e reaproveitar.
10. `_text_like_mask` faz `glyph_mask[labels == label] = 255` dentro de um laço, O(componentes × pixels). Em página escaneada isso explode. Correção: tabela de consulta vetorizada.
11. `keep_region` roda duas vezes para regiões estruturais.
12. Uma exceção numa página derruba o documento inteiro. Correção: try/except por página, registrando a página como falha.
13. `extract_figures` devolve todos os PNGs do livro em memória. Falta um `iter_pages()` para gravar página a página.
14. O motivo da rejeição (`keep_region` → `"tabela"`, `"pequena demais"`…) é descartado. Expor isso num modo debug acelera a calibração.
15. Os limiares em pixels assumem 160 dpi: `_is_typeset_block` (12–50 px, mínimo de 80 px) e `_text_like_mask` (h ≤ 28 px). Ou se normaliza pelo dpi, ou se proíbe `page_images` em outro dpi.
16. Ícones e mascotes repetidos (o mesmo xref em dezenas de páginas) não são deduplicados. Contar a frequência do xref no documento resolve.
17. Empacotamento:
    - O núcleo depende de `fastapi`, `uvicorn` e `python-docx`, que vêm do inspetor e do docx. É preciso separar em extras (`[inspector]`, `[docx]`).
    - `opencv-python-headless` entra como dependência nova no worker (cerca de 60 MB na imagem).
    - O repositório não tem remote.
18. Não existe teste com livro real. Os testes usam só o PDF sintético. Faltam testes "golden" com as páginas citadas acima.

## 3. Plano de integração (sem quebrar o Linear)

Princípio: o extrator novo entra **atrás de uma flag, com o mesmo contrato de saída** (`ExtractedPdfImage`). Tudo depois de `extract_images` (upload, `figures`, `describe`, `_resolve_targets`, Dorina) continua igual. O caminho atual não muda até a comparação provar o ganho.

### Fase 0: preparar o extrator (no repositório extrator-figuras)

**Feita** nos commits `2d41ae3` e `8aeb965` do extrator-figuras.

1. ~~Commitar o trabalho pendente.~~ Feito. Não foi criada tag; a versão é o hash do commit.
2. ~~Corrigir os P0 (itens 1 a 6) e os itens 9, 10 e 12, com testes golden das páginas reais.~~ Feito.
   - Ajuste no item 2: o recorte só é aparado pela transparência quando há texto atrás, e o tamanho continua sendo julgado pela imagem cheia. Aparar sempre fazia fileiras finas (caminhões, livros) caírem no lado mínimo.
   - Ajuste no item 4: "bloco de texto" passou a exigir linhas de mesma altura ou margem alinhada.
3. ~~Criar `iter_pages(pdf, options)`.~~ Feito. O motivo de rejeição em modo debug ficou para depois.
4. Mover `fastapi`, `uvicorn` e `python-docx` para extras: **pendente**. Não afeta o Linear, que vendoriza só o pacote.
5. **Novo:** imagens pequenas em grade ou mosaico.
   - Cédulas, fotos de animais e o labirinto de casinhas eram descartados pela área mínima.
   - Agora entram quando são 2 ou mais imagens agrupadas.
   - Repetidas ou encostadas viram uma figura só; diferentes e separadas, uma figura cada.

Ainda em aberto no extrator: legenda (item 7), âncora (item 8), limiares em pixels (item 15), ícones repetidos (item 16), blocos de centena tratados como tabela (Matemática p. 128).

### Fase 1: trazer para o Linear, desligado

**Feita** no branch `feat/extrator-figuras-v3`. Pendente só conferir o build do Docker.

5. **Vendorizar** o pacote em `src/vendor/pdf_figure_extractor/`, já que não há remote para dependência via git. O README da pasta registra o commit de origem e como atualizar.
6. Adicionar ao `requirements.txt` o `opencv-python-headless==5.0.0.93` e conferir o build do `Dockerfile.worker` (python:3.11-slim). **O build não foi testado**, porque não havia Docker na máquina.
7. Criar o adaptador `src/pipeline/steps/pdf_figures_v3.py` com `extract_images_v3(pdf_bytes, render_fallback_dpi) -> list[ExtractedPdfImage]`:
   - `image_index` na ordem de leitura (`reading_order`).
   - `kind="raster"` para `pdf_xobject` e `hybrid`, `"vector"` para os demais.
   - `source_key` com o bbox, no mesmo padrão de hoje.
   - Manter o fallback de página inteira, porque `describe.py:329-334` só liga o contexto de figuras quando `figure_keys` não está vazio. Remover o fallback muda o comportamento e fica para outra decisão.
   - Não passar o raster cinza do Linear em `page_images`: o extrator rasteriza sozinho, uma página por vez.
   - Devolver por figura `{bbox, caption, anchor, source, confidence}` no campo novo `ExtractedPdfImage.meta`, que aparece como `extraction` na entrada da figura.
   - Importar o extrator só quando o v3 é usado: sem OpenCV no container, o worker sobe e só o v3 falha.
8. Criar a flag `PDF_FIGURE_EXTRACTOR=legacy|v3` em `config.py`, com padrão `legacy`, nos arquivos `.env.example`, `deploy/aws/env.worker.example` e `task-definition.worker.json`. Criar também o override por job: `jobs.metadata.figure_extractor`, lido em `v2_orchestrator.py:84-88` e passado via `ctx`.
9. Em `extract_images.py`:
   - Escolher o extrator pela flag.
   - Se o v3 falhar por inteiro, usar o extrator legacy, para o job não falhar.
   - Gravar `"figure_extractor"` (`legacy` ou `v3@<commit>`) no `extract_checkpoint.json` **só como registro**.
   - **Mudança em relação ao plano original:** o checkpoint não é invalidado quando o extrator muda. Ele é do job (`json/{isbn}/{pv}/{job_id}/`). Invalidá-lo faria um retry renumerar as figuras por baixo de uma linearização já salva, que é o que a trava "já tem linearização" impede. A flag vale para jobs novos.
10. Guardar os metadados novos (bbox, caption, anchor) no checkpoint, dentro de cada figura. O `figures_manifest.json` separado não foi feito, e o banco não foi mexido nesta fase.

### Fase 2: comparar antes de ligar

11. Criar `scripts/compare_figure_extractors.py`. Ele roda os dois extratores no mesmo PDF e gera um HTML com, por página: miniatura, caixas de cada extrator e recortes. Mostra também as contagens e a taxa de fallback de página inteira. Revisão humana nos três livros acima, mais um ou dois de outras disciplinas, incluindo um escaneado.
12. Rodar jobs reais com `metadata.figure_extractor = "v3"` em modo `test_run` e comparar:
    - Quantos `source:"page_fallback"` a Dorina recebeu.
    - Quantas descrições falharam.
    - Uma amostra de descrições lidas por quem revisa, para ver se a figura descrita é a figura certa.
13. Critério para virar padrão: menos `page_fallback`, nenhuma figura de conteúdo perdida na amostra revisada e tempo extra por livro aceitável. A estimativa é de 2 a 4 min, pequeno perto do tempo de OpenAI e Dorina.

### Fase 3: ligar e aproveitar o contexto

14. Trocar o padrão para `v3` e manter `legacy` disponível por pelo menos dois ciclos de produção.
15. Em `_build_dorina_context` (`describe.py:211`), usar `caption` e `credit` do extrator quando a IA não devolver `legenda`.
16. Opcional: mandar no prompt de linearização a ordem das figuras ("fig1 = topo-esquerda…") para reduzir o casamento por posição.
17. Opcional: migração adicionando `bbox` e `caption` em `figures`.

### O que fica de fora ou precisa de decisão

- `src/pipeline/test_run.py` e `lib/test-pdf-prepare.ts` (o extrator em PDF.js no navegador) duplicam a extração. O caminho do navegador não roda OpenCV, então os testes serverless vão divergir do worker até se decidir se essa extração passa para o worker.
- O fallback de página inteira: manter ou remover, conforme o item 7.
