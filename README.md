# Bairro em Dia — Assistente Conversacional CitizenTech (RAG)

**Global Solution 2026.2 · Generative AI & Advanced Nets · FIAP · Turma 2TIAPF**

| Integrante | RM |
|---|---|
| Gabriel Tonelli Avelino dos Santos | 564705 |
| Marcelo Roberto Maso Junior | 562163 |
| Vinícius Adrian Siqueira de Oliveira | 564962 |

O **Bairro em Dia** é um app para moradores relatarem problemas do bairro (buracos, iluminação com defeito, lixo acumulado, incômodo sonoro). O morador informa o local, descreve o problema e pode anexar fotos ou áudio. A IA organiza e classifica o relato e gera um protocolo que o morador e o gestor acompanham. Um **assistente conversacional com RAG** orienta o cidadão sobre como buscar atendimento nos canais oficiais da Prefeitura de São Paulo, citando as fontes e se abstendo quando não há evidência.

## Arquitetura

```
Relato / pergunta do cidadão
   │
   ├─ Guardrails de entrada: mascaramento de PII (CPF, telefone, e-mail, cartão) · detecção de prompt injection
   ├─ Reescrita de pergunta de continuação ("e o prazo?" → herda o tema anterior)
   ├─ Retriever híbrido: BM25 (Snowball PT + expansão de vocabulário) ⊕ denso (embeddings) via RRF
   │     + reforço por intenção de seção (prazo, documentos, canais…) · filtro por categoria do relato
   ├─ Portões: ambiguidade → pede esclarecimento · relevância baixa → abstenção · lugar fora da base → abstenção
   ├─ Generator: Gemini (temperatura 0,1) com prompt de papel, regras de citação [n] e abstenção
   └─ Verificação de saída: citações válidas · números presentes nas fontes · sobreposição com as fontes ·
         canário anti-vazamento · dado pedido presente → retry → fallback extrativo → abstenção
```

## Estrutura

```
corpus/docs/          12 documentos oficiais (Markdown + metadados: órgão, categoria, URL, datas)
corpus/adversarial/   documento envenenado usado só no teste de injection indireto
src/bairro_rag/       corpus.py (chunking) · retriever.py · generator.py · guardrails.py · classifier.py · assistant.py
app/streamlit_app.py  protótipo: relatar problema, acompanhar protocolo, assistente, painel do gestor
eval/                 questions.json (dev, 36) · questions_teste.json (teste separado, 15) · security_tests.json (7) · run_eval.py
results/              métricas e respostas por pergunta (historico_v1/ = 1ª rodada, antes das correções)
notebook_bairro_em_dia.ipynb   execução completa no Google Colab
CORPUS.md             fontes, URLs e datas de consulta
```

## Como executar (Windows / PowerShell)

```powershell
cd bairro-em-dia-rag
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Chave do Gemini (opcional — sem ela o generator extrativo offline é usado).
# Opção 1 (recomendada): copie .env.example para .env e preencha GEMINI_API_KEY
Copy-Item .env.example .env
notepad .env
# Opção 2: só para a janela atual do PowerShell
$env:GEMINI_API_KEY = "sua-chave-aqui"

# Protótipo
streamlit run app/streamlit_app.py

# Avaliação completa (conjunto de desenvolvimento + conjunto de teste)
python eval/run_eval.py --backend auto
python eval/run_eval.py --backend auto --set teste
```

No Google Colab, abra `notebook_bairro_em_dia.ipynb` e cadastre `GEMINI_API_KEY` em *Secrets*.

**Credenciais:** a chave é lida apenas de variável de ambiente; nunca é gravada no código nem no repositório (`.env` está no `.gitignore`).

## Configuração final

| Componente | Escolha |
|---|---|
| Chunking | Estrutural por seção (`##`), listas longas em grupos de 4 itens, fusão de seções vizinhas do mesmo documento até 150 palavras; prefixo com título + seção; metadados preservados |
| Retriever | Híbrido BM25 (k1 = 1,5, b = 0,75) + denso `paraphrase-multilingual-MiniLM-L12-v2`, fusão RRF (k = 60), top-k = 4, expansão de vocabulário, reforço por intenção de seção |
| Generator | Gemini Flash mais recente disponível para a chave, escolhido automaticamente (ou `GEMINI_MODEL`; versão real registrada em `model_version`), temperatura 0,1, top-p 0,9, até 600 tokens |
| Abstenção | BM25 do topo < 3,5 **e** similaridade densa < 0,75 → não chama o LLM |

> Sem acesso ao modelo de embeddings, o retriever denso cai automaticamente para LSA (TF-IDF de n-gramas de caracteres + SVD). Os resultados em `results/` foram gerados nesse modo e com o generator extrativo. Rode o notebook com internet e chave para obter os números com embeddings neurais e Gemini.

## Problemas comuns

**Terminal cheio de `ModuleNotFoundError: No module named 'torchvision'` ao rodar o Streamlit.** É só ruído: o *file watcher* do Streamlit inspeciona os módulos de visão do `transformers` (carregado pelo `sentence-transformers`), e o app funciona normalmente. O arquivo `.streamlit/config.toml` do projeto já desliga o watcher; rode o `streamlit run` **a partir da raiz do projeto** para ele ser lido. Alternativa pontual:

```powershell
streamlit run app/streamlit_app.py --server.fileWatcherType none
```
