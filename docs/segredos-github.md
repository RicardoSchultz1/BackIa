# Guia de Segredos para Subir no GitHub

Este documento define como guardar e usar chaves sem vazar credenciais no repositório.

## 1. Regra Principal

- Nunca commitar chaves reais.
- O arquivo `.env` deve ficar apenas local.
- O arquivo `.env.example` deve ter somente placeholders.

## 2. Onde Guardar as Chaves Reais

- Desenvolvimento local: arquivo `.env` (já ignorado no Git).
- CI/CD no GitHub: `Settings -> Secrets and variables -> Actions`.

## 3. Lista de Segredos Recomendados no GitHub

- `REDIS_URL`
- `JAVA_API_TOKEN`
- `DATABASE_URL`
- `SUPABASE_URL`
- `SUPABASE_API_KEY`
- `SUPABASE_STORAGE_BUCKET`

Observacao:

- `REDIS_QUEUE_NAME`, `STATUS_ID_UPLOADED`, `STATUS_ID_PROCESSING`, `STATUS_ID_PROCESSED`, `STATUS_ID_FAILED`, `QA_DEFAULT_TOP_K` e `QA_MAX_TOP_K` normalmente nao sao segredos. Eles podem ficar em `.env.example` com valores padrao.

## 4. Como Publicar sem Risco

1. Preencha apenas `.env` com valores reais.
2. Mantenha `.env.example` com placeholders.
3. Antes de push, valide se não há segredo exposto:

```powershell
git grep -n "sb_secret_|postgresql://|SUPABASE_API_KEY|DATABASE_URL|redis://"
```

4. Faça commit e push normalmente.

## 5. Se Alguma Chave Vazar

1. Rotacione a chave imediatamente no provedor (Supabase/API).
2. Remova o valor do código e histórico recente.
3. Gere nova credencial e atualize `.env` local e GitHub Secrets.

## 6. Exemplo Seguro de `.env.example`

```dotenv
REDIS_URL=redis://localhost:6379/0
REDIS_QUEUE_NAME=document_jobs
DATABASE_URL=postgresql://<db_user>:<db_password>@<pooler_host>:6543/postgres?sslmode=require&pgbouncer=true
SUPABASE_URL=https://<project_ref>.supabase.co
SUPABASE_API_KEY=<supabase_service_role_or_secret_key>
SUPABASE_STORAGE_BUCKET=<bucket_name>
JAVA_API_TOKEN=<java_api_token>
STATUS_ID_UPLOADED=1
STATUS_ID_PROCESSING=2
STATUS_ID_PROCESSED=3
STATUS_ID_FAILED=4
QA_DEFAULT_TOP_K=5
QA_MAX_TOP_K=10
```
