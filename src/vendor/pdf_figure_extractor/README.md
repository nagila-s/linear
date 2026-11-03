# pdf_figure_extractor (vendorizado)

Cópia do pacote `pdf_figure_extractor` do repositório **extrator-figuras**
(`~/Documents/extrator-figuras`, sem remote), commit `8aeb965`.

Vendorizado porque o repositório não tem remote de onde o Docker possa instalar.
Ficaram de fora a CLI, o inspetor (FastAPI) e o `__main__`; `demo_pdf.py`
entra porque os testes usam o PDF sintético.

**Não edite aqui.** Corrija no extrator-figuras, rode os testes de lá e copie de novo:

```bash
for f in __init__ annotate consumers demo_pdf detect extract filters geometry models pdf_ops; do
  cp ~/Documents/extrator-figuras/pdf_figure_extractor/$f.py src/vendor/pdf_figure_extractor/
done
sed -i '' -E 's/^from pdf_figure_extractor\.([a-z_]+) import/from .\1 import/' src/vendor/pdf_figure_extractor/*.py
```

Atualize o commit acima e `EXTRACTOR_VERSION` em `src/pipeline/steps/pdf_figures_v3.py`
(é o que invalida o checkpoint de extração de jobs antigos).
