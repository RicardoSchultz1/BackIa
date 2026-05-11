# Documentacao de Integracao do Worker e API de Consulta

 Este documento descreve o contrato atual do servico Python responsavel por:

 - consumir jobs de processamento de documentos
 - extrair texto e gerar embeddings
 - persistir chunks no banco
 - sincronizar status com a API Java
 - responder perguntas e buscas semanticas sobre os documentos processados

 ## 1. Visao Geral da Arquitetura

 O projeto possui dois fluxos principais:

 1. Ingestao de documentos via Redis ou `jobs.jsonl`
 2. Consulta semantica via API HTTP FastAPI

 Fluxo resumido:

 1. O backend Java grava um registro em `arquivo`
 2. O backend Java publica um job no Redis com `document_id` e `file_path`
 3. O worker Python consome esse job
 4. O worker extrai texto, gera chunks e embeddings
 5. O worker persiste os dados em `document_chunks`
 6. O worker atualiza o status do documento no backend Java
 7. A API de Q&A consulta `document_chunks` para responder perguntas e buscar documentos similares

 ## 2. Entrada do Worker

 O worker consome um job por vez a partir do Redis ou de um arquivo de polling (`jobs.jsonl`).

 ### Formato do payload

 ```json
 {
   "document_id": 123,
   "file_path": "files/contrato.pdf"
 }
 ```

 ### Campos esperados

 | Campo | Tipo | Obrigatorio | Descricao |
 | --- | --- | --- | --- |
 | `document_id` | integer | Sim | Identificador do documento na tabela `arquivo` |
 | `file_path` | string | Sim | Caminho absoluto ou relativo do arquivo a ser processado |

 ### Validacao esperada

 | Regra | Resultado esperado |
 | --- | --- |
 | `document_id` ausente ou invalido | Job falha durante parsing |
 | `file_path` ausente | Job falha durante parsing |
 | Arquivo nao existe no disco | Worker tenta Supabase Storage; se nao encontrar, marca como `FAILED` |
 | Arquivo sem texto extraivel | Worker marca como `FAILED` |

 ### Origem do arquivo

 O worker tenta resolver o `file_path` nesta ordem:

 1. Disco local
 2. `FILES_BASE_PATH` quando o caminho do job for relativo
 3. Supabase Storage (`SUPABASE_URL` + `SUPABASE_API_KEY` + `SUPABASE_STORAGE_BUCKET`)

 ### Exemplo de envio via Redis

 Fila/lista: `document_jobs`

 ```json
 {"document_id":123,"file_path":"files/contrato.pdf"}
 ```

 Exemplo em Python:

 ```python
 import json
 import redis

 r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
 payload = {"document_id": 123, "file_path": "files/contrato.pdf"}
 r.lpush("document_jobs", json.dumps(payload))
 ```

 Exemplo em Redis CLI:

 ```bash
 LPUSH document_jobs "{\"document_id\":123,\"file_path\":\"files/contrato.pdf\"}"
 ```

 ### Exemplo de envio via polling (`jobs.jsonl`)

 Uma linha JSON por job:

 ```json
 {"document_id":123,"file_path":"files/contrato.pdf"}
 ```

 ## 3. Fluxo de Processamento

 Para cada job recebido, o worker executa a seguinte sequencia:

 1. Atualiza o status para `PROCESSING`
 2. Extrai texto do arquivo
 3. Cria chunks
 4. Gera embeddings
 5. Remove chunks antigos do documento
 6. Insere os novos chunks na tabela `document_chunks`
 7. Atualiza o status para `PROCESSED`

 Se qualquer etapa falhar, o worker tenta novamente ate `MAX_RETRIES`. Apos esgotar as tentativas, envia status `FAILED`.

 Observacao: o fluxo atual nao usa mais um endpoint separado de `complete`.

 ## 4. Atualizacao de Status no Backend Java

 ### Endpoint

 ```http
 PUT /arquivos/{id}/status
 ```

 ### Headers esperados

 ```http
 Content-Type: application/json
 Authorization: Bearer <token>    # opcional
 ```

 ### Payload enviado pelo worker

 O worker envia `statusId`, nao o nome textual do status.

 Exemplo:

 ```json
 {
   "statusId": 2
 }
 ```

 ### Mapeamento padrao no worker

 | Status logico | Variavel de ambiente | Valor padrao |
 | --- | --- | --- |
 | `UPLOADED` | `STATUS_ID_UPLOADED` | `1` |
 | `PROCESSING` | `STATUS_ID_PROCESSING` | `2` |
 | `PROCESSED` | `STATUS_ID_PROCESSED` | `3` |
 | `FAILED` | `STATUS_ID_FAILED` | `4` |

 Se os IDs reais do banco forem diferentes, ajuste o `.env` do worker.

 ### Resposta esperada pelo worker

 O worker aceita qualquer resposta HTTP `2xx`. O corpo da resposta e opcional.

 ### Respostas de erro esperadas

 | HTTP Status | Quando usar | Comportamento do worker |
 | --- | --- | --- |
 | `400 Bad Request` | Payload invalido | Retry ate o limite configurado |
 | `401 Unauthorized` | Token ausente ou invalido | Retry ate o limite configurado |
 | `404 Not Found` | Documento inexistente | Retry ate o limite configurado |
 | `500 Internal Server Error` | Erro interno do backend | Retry ate o limite configurado |

 ## 5. Saida Persistida no Banco

 O worker salva os resultados na tabela `document_chunks`.

 ### Colunas utilizadas

 | Coluna | Tipo esperado | Descricao |
 | --- | --- | --- |
 | `document_id` | integer / bigint | ID do documento na tabela `arquivo` |
 | `chunk_index` | integer | Indice sequencial do chunk, comecando em 0 |
 | `chunk_text` | text | Conteudo textual do chunk |
 | `page_number` | integer nullable | Pagina de origem, quando disponivel |
 | `embedding` | vector(384) | Embedding gerado pelo modelo `all-MiniLM-L6-v2` |
 | `created_at` | timestamp | Data de criacao do registro |
 | `updated_at` | timestamp | Data de atualizacao do registro |

 ### Comportamento esperado de persistencia

 | Situacao | Resultado esperado |
 | --- | --- |
 | Reprocessamento do mesmo documento | Os chunks antigos sao removidos antes da nova insercao |
 | Documento sem chunks | Nenhum registro e inserido |
 | Quantidade de embeddings diferente da quantidade de chunks | Processamento falha |

 ## 6. Estados de Processamento

 | Status | Origem | Significado |
 | --- | --- | --- |
 | `PROCESSING` | Worker -> API Java | Documento aceito e em processamento |
 | `PROCESSED` | Worker -> API Java | Documento processado com sucesso |
 | `FAILED` | Worker -> API Java | Falha definitiva apos esgotar as tentativas |

 ## 7. Arquivos Suportados

 | Tipo | Extensoes | Estrategia de extracao |
 | --- | --- | --- |
 | PDF | `.pdf` | `pdfplumber` |
 | Imagem | `.png`, `.jpg`, `.jpeg` | `pytesseract` |
 | Excel | `.xls`, `.xlsx`, `.xlsm` | `pandas` |
 | Word | `.docx` | `python-docx` |

 Observacao: arquivos `.doc` legados nao sao processados pelo worker atual e resultam em falha.

 ## 8. API de Perguntas e Respostas

 A API HTTP de consulta usa FastAPI e consulta os dados ja indexados em `document_chunks`.

 ### Subir a API

 ```powershell
 pip install -r requirements.txt
 python -m uvicorn qa_api:app --host 0.0.0.0 --port 8001
 ```

 ### Healthcheck

 ```http
 GET /health
 ```

 Resposta:

 ```json
 {
   "status": "ok"
 }
 ```

 ### Endpoint de pergunta

 ```http
 POST /ask
 ```

 Payload:

 ```json
 {
   "question": "O que o documento fala sobre redis?",
   "document_id": 2,
   "top_k": 5
 }
 ```

 Campos:

 | Campo | Tipo | Obrigatorio | Descricao |
 | --- | --- | --- | --- |
 | `question` | string | Sim | Pergunta em linguagem natural |
 | `document_id` | integer | Nao | Restringe a busca a um documento especifico |
 | `top_k` | integer | Nao | Quantidade de chunks relevantes a recuperar |

 Resposta:

 ```json
 {
   "answer": "Resposta baseada nos trechos mais relevantes...",
   "sources": [
     {
       "document_id": 2,
       "chunk_index": 0,
       "page_number": 1,
       "similarity": 0.95,
       "chunk_text": "Trecho encontrado...",
       "arquivo_nome": "teste_worker.xlsx",
       "arquivo_path": "C:/dados/teste_worker.xlsx",
       "download_url": "/download/2"
     }
   ]
 }
 ```

 ### Endpoint de busca por descricao de arquivo

 ```http
 POST /search
 ```

 Payload:

 ```json
 {
   "description": "planilha com informacoes sobre pipeline e redis",
   "limit": 5
 }
 ```

 Resposta:

 ```json
 {
   "documents": [
     {
       "document_id": 2,
       "arquivo_nome": "teste_worker.xlsx",
       "arquivo_path": "C:/dados/teste_worker.xlsx",
       "max_similarity": 0.88,
       "avg_similarity": 0.74,
       "chunk_count": 3,
       "download_url": "/download/2"
     }
   ]
 }
 ```

 Campos de resposta:

 | Campo | Descricao |
 | --- | --- |
 | `max_similarity` | Melhor similaridade encontrada entre os chunks do documento |
 | `avg_similarity` | Similaridade media dos chunks daquele documento |
 | `chunk_count` | Quantidade de chunks daquele documento considerados na agregacao |
 | `download_url` | Endpoint de download do arquivo |

 ### Endpoint de download

 ```http
 GET /download/{document_id}
 ```

 Retorna o arquivo fisico associado ao registro em `arquivo.path`, quando o caminho existir no sistema de arquivos local.

 ## 9. Variaveis de Ambiente Relevantes

 ### Worker e fila

 ```dotenv
 WORKER_MODE=redis
 REDIS_URL=redis://localhost:6379/0
 REDIS_QUEUE_NAME=document_jobs
 POLLING_JOB_FILE=jobs.jsonl
 POLLING_INTERVAL_SECONDS=5
 MAX_RETRIES=3
 ```

 ### API Java

 ```dotenv
 JAVA_API_BASE_URL=http://localhost:8081
 JAVA_API_TIMEOUT_SECONDS=30
 JAVA_API_TOKEN=
 STATUS_ID_UPLOADED=1
 STATUS_ID_PROCESSING=2
 STATUS_ID_PROCESSED=3
 STATUS_ID_FAILED=4
 ```

 ### Banco e Storage

 ```dotenv
 DATABASE_URL=postgresql://<db_user>:<db_password>@<pooler_host>:6543/postgres?sslmode=require&pgbouncer=true
 DB_CONNECT_TIMEOUT_SECONDS=10
 SUPABASE_URL=https://<project_ref>.supabase.co
 SUPABASE_API_KEY=<supabase_service_role_or_secret_key>
 SUPABASE_STORAGE_BUCKET=<bucket_name>
 SUPABASE_STORAGE_TIMEOUT_SECONDS=60
 ```

 ### Embeddings e Q&A

 ```dotenv
 EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2
 EMBEDDING_BATCH_SIZE=16
 QA_DEFAULT_TOP_K=5
 QA_MAX_TOP_K=10
 CHUNK_MAX_TOKENS=500
 ```

 ## 10. Exemplo de Fluxo Completo

 ### 1. Backend Java grava o arquivo e publica o job no Redis

 ```json
 {
   "document_id": 123,
   "file_path": "files/contrato.pdf"
 }
 ```

 ### 2. Worker consome a fila

 Operacao Redis usada pelo worker:

 ```bash
 BRPOP document_jobs 5
 ```

 ### 3. Worker atualiza status para processamento

 ```http
 PUT /arquivos/123/status
 ```

 ```json
 {
   "statusId": 2
 }
 ```

 ### 4. Worker processa o arquivo e persiste os chunks

 Resultado esperado: registros em `document_chunks` com embeddings e timestamps.

 ### 5. Worker atualiza status final

 ```http
 PUT /arquivos/123/status
 ```

 ```json
 {
   "statusId": 3
 }
 ```

 ### 6. Cliente consulta a API de perguntas

 ```http
 POST /ask
 ```

 ou busca documentos similares:

 ```http
 POST /search
 ```

 ## 11. Observacoes de Compatibilidade

 | Item | Recomendacao |
 | --- | --- |
 | Codigo de sucesso da API Java | Retornar `200`, `201` ou `204` |
 | Corpo da resposta de status | Pode ser vazio, desde que o status seja `2xx` |
 | Timeout | A API Java deve responder dentro do timeout configurado no worker |
 | Autenticacao | Se habilitada, usar `Authorization: Bearer <token>` |
 | Redis | Java e Python devem apontar para a mesma instancia e mesma fila |
 | Download de arquivos | O endpoint `/download/{document_id}` depende de `arquivo.path` existir localmente |

### Campos esperados

| Campo | Tipo | Obrigatório | Descrição |
| --- | --- | --- | --- |
| `document_id` | integer | Sim | Identificador do documento no backend Java/Supabase |
| `file_path` | string | Sim | Caminho absoluto ou relativo do arquivo a ser processado |

### Validação esperada

| Regra | Resultado esperado |
| --- | --- |
| `document_id` ausente ou inválido | Job falha durante parsing |
| `file_path` ausente | Job falha durante parsing |
| Arquivo não existe no disco | Worker marca o documento como `FAILED` |
| Arquivo sem texto extraível | Worker marca o documento como `FAILED` |

### Origem do arquivo

O worker tenta resolver o `file_path` nesta ordem:

1. Disco local (caminho absoluto ou relativo com `FILES_BASE_PATH`)
2. Supabase Storage (`SUPABASE_URL` + `SUPABASE_API_KEY` + `SUPABASE_STORAGE_BUCKET`)

Se o arquivo não existir localmente e as variáveis de Storage estiverem configuradas, o worker faz download temporário do objeto no bucket e processa normalmente.

### Exemplo de envio via Redis

Lista/queue: `document_jobs`

```json
{"document_id":123,"file_path":"/files/doc1.pdf"}
```

### Exemplo de envio via polling (`jobs.jsonl`)

Uma linha JSON por job:

```json
{"document_id":123,"file_path":"/files/doc1.pdf"}
```

## 2. Fluxo de Saída do Worker

Para cada job recebido, o worker executa a seguinte sequência:

1. Atualiza o status para `PROCESSING`
2. Extrai texto do arquivo
3. Gera `content_hash`
4. Cria chunks
5. Gera embeddings
6. Persiste os chunks na tabela `document_chunks`
7. Notifica o backend Java sobre a conclusão
8. Atualiza o status para `PROCESSED`

Se qualquer etapa falhar, o worker tenta novamente até `MAX_RETRIES`. Após esgotar as tentativas, envia status `FAILED`.

## 3. Requisição para Atualização de Status

### Endpoint

```http
PATCH /documents/{id}/status
```

### Headers esperados

```http
Content-Type: application/json
Authorization: Bearer <token>    # opcional
```

### Requisição: documento em processamento

```json
{
  "status": "PROCESSING"
}
```

### Requisição: documento processado

```json
{
  "status": "PROCESSED"
}
```

### Requisição: documento com falha

```json
{
  "status": "FAILED",
  "error_message": "File not found: /files/doc1.pdf"
}
```

### Resposta esperada pelo worker

O worker aceita qualquer resposta HTTP `2xx`. O corpo da resposta é opcional.

### Exemplo de resposta de sucesso

```http
200 OK
Content-Type: application/json
```

```json
{
  "document_id": 123,
  "status": "PROCESSING",
  "updated": true
}
```

### Exemplo alternativo de resposta válida

```http
204 No Content
```

### Respostas de erro esperadas

| HTTP Status | Quando usar | Comportamento do worker |
| --- | --- | --- |
| `400 Bad Request` | Payload inválido | Retry até o limite configurado |
| `401 Unauthorized` | Token ausente/inválido | Retry até o limite configurado |
| `404 Not Found` | Documento inexistente | Retry até o limite configurado |
| `500 Internal Server Error` | Erro interno do backend | Retry até o limite configurado |

### Exemplo de resposta de erro

```http
400 Bad Request
Content-Type: application/json
```

```json
{
  "message": "Invalid status value"
}
```

## 4. Requisição de Conclusão do Documento

### Endpoint

```http
POST /documents/{id}/complete
```

### Headers esperados

```http
Content-Type: application/json
Authorization: Bearer <token>    # opcional
```

### Requisição

```json
{
  "content_hash": "6f1f2f13d44a2f6b0f0f6200d8fdb0b3d2d5a94a735d8b1f9d01c8f9b2b44f10",
  "chunk_count": 8
}
```

### Campos esperados

| Campo | Tipo | Obrigatório | Descrição |
| --- | --- | --- | --- |
| `content_hash` | string | Sim | SHA-256 do texto extraído do documento |
| `chunk_count` | integer | Sim | Quantidade total de chunks persistidos |

### Resposta esperada pelo worker

O worker aceita qualquer resposta HTTP `2xx`. O corpo da resposta é opcional.

### Exemplo de resposta de sucesso

```http
200 OK
Content-Type: application/json
```

```json
{
  "document_id": 123,
  "completed": true,
  "content_hash": "6f1f2f13d44a2f6b0f0f6200d8fdb0b3d2d5a94a735d8b1f9d01c8f9b2b44f10",
  "chunk_count": 8
}
```

### Exemplo alternativo de resposta válida

```http
204 No Content
```

### Respostas de erro esperadas

| HTTP Status | Quando usar | Comportamento do worker |
| --- | --- | --- |
| `400 Bad Request` | Hash ou chunk_count inválidos | Retry até o limite configurado |
| `401 Unauthorized` | Token ausente/inválido | Retry até o limite configurado |
| `404 Not Found` | Documento inexistente | Retry até o limite configurado |
| `409 Conflict` | Documento já finalizado ou estado inconsistente | Retry até o limite configurado |
| `500 Internal Server Error` | Erro interno do backend | Retry até o limite configurado |

## 5. Saída Persistida no Banco

O worker salva os resultados na tabela `document_chunks`.

### Tabela alvo

```sql
document_chunks
```

### Colunas utilizadas

| Coluna | Tipo esperado | Descrição |
| --- | --- | --- |
| `document_id` | integer / bigint | ID do documento no backend |
| `chunk_index` | integer | Índice sequencial do chunk, começando em 0 |
| `chunk_text` | text | Conteúdo textual do chunk |
| `page_number` | integer nullable | Página de origem, quando disponível |
| `embedding` | vector(384) | Embedding gerado pelo modelo `all-MiniLM-L6-v2` |

### Comportamento esperado de persistência

| Situação | Resultado esperado |
| --- | --- |
| Reprocessamento do mesmo documento | Os chunks antigos são removidos antes da nova inserção |
| Documento sem chunks | Nenhum registro é inserido |
| Quantidade de embeddings diferente da quantidade de chunks | Processamento falha |

### Exemplo de registro persistido

```json
{
  "document_id": 123,
  "chunk_index": 0,
  "chunk_text": "Este e o texto do primeiro chunk do documento.",
  "page_number": 1,
  "embedding": [0.0123, -0.0456, 0.0789]
}
```

Observação: o vetor real possui 384 dimensões.

## 6. Estados de Processamento

| Status | Origem | Significado |
| --- | --- | --- |
| `PROCESSING` | Worker -> API Java | Documento aceito e em processamento |
| `PROCESSED` | Worker -> API Java | Documento processado com sucesso |
| `FAILED` | Worker -> API Java | Falha definitiva após esgotar as tentativas |

## 7. Arquivos Suportados

| Tipo | Extensões | Estratégia de extração |
| --- | --- | --- |
| PDF | `.pdf` | `pdfplumber` |
| Imagem | `.png`, `.jpg`, `.jpeg` | `pytesseract` |
| Excel | `.xls`, `.xlsx`, `.xlsm` | `pandas` |
| Word | `.docx` | `python-docx` |

Observação: arquivos `.doc` legados não são processados pelo worker atual e resultam em falha.

## 8. Exemplo de Fluxo Completo

### 1. Job recebido

```json
{
  "document_id": 123,
  "file_path": "/files/contrato.pdf"
}
```

### 2. Chamada de status inicial

```http
PATCH /documents/123/status
```

```json
{
  "status": "PROCESSING"
}
```

### 3. Chamada de conclusão

```http
POST /documents/123/complete
```

```json
{
  "content_hash": "6f1f2f13d44a2f6b0f0f6200d8fdb0b3d2d5a94a735d8b1f9d01c8f9b2b44f10",
  "chunk_count": 8
}
```

### 4. Chamada de status final

```http
PATCH /documents/123/status
```

```json
{
  "status": "PROCESSED"
}
```

## 9. Observações de Compatibilidade

| Item | Recomendação |
| --- | --- |
| Código de sucesso da API Java | Retornar `200`, `201` ou `204` |
| Corpo da resposta | Pode ser vazio, desde que o status seja `2xx` |
| Timeout | A API Java deve responder dentro do timeout configurado no worker |
| Autenticação | Se habilitada, usar `Authorization: Bearer <token>` |

## 10. Configuração Supabase

Exemplo de configuração para o worker Python com Supabase PostgreSQL (pooler):

```dotenv
DATABASE_URL=postgresql://<db_user>:<db_password>@<pooler_host>:6543/postgres?sslmode=require&pgbouncer=true
DB_CONNECT_TIMEOUT_SECONDS=10
SUPABASE_URL=https://<project_ref>.supabase.co
SUPABASE_API_KEY=<supabase_service_role_or_secret_key>
SUPABASE_STORAGE_BUCKET=<bucket_name>
SUPABASE_STORAGE_TIMEOUT_SECONDS=60
```

Mapeamento das propriedades Spring para este worker:

| Spring Boot | Worker Python |
| --- | --- |
| `spring.datasource.url` | `DATABASE_URL` |
| `spring.datasource.username` + `spring.datasource.password` | Credenciais embutidas em `DATABASE_URL` |
| `spring.datasource.hikari.data-source-properties.prepareThreshold=0` | Não aplicável diretamente no `psycopg2` atual |
| `spring.datasource.hikari.data-source-properties.preferQueryMode=simple` | Não aplicável diretamente no `psycopg2` atual |
| `supabase.url` | `SUPABASE_URL` |
| `supabase.api-key` | `SUPABASE_API_KEY` |
