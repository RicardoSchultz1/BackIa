# Documentação de Requisições e Respostas do Worker

Este documento descreve o contrato de entrada e saída do serviço Python responsável por processar documentos, gerar embeddings e sincronizar o status com a API Java.

## 1. Entrada do Worker

O worker consome um job por vez a partir do Redis ou de um arquivo de polling (`jobs.jsonl`).

### Formato do payload

```json
{
  "document_id": 123,
  "file_path": "/files/doc1.pdf"
}
```

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
