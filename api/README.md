# PavimentAI — API

Plataforma para cidadãos registrarem problemas de infraestrutura urbana (buracos e problemas de
acessibilidade), com vários municípios na mesma plataforma e dados isolados por cidade.

**Tecnologias:** Python 3.14, FastAPI, PostgreSQL com PostGIS, Pillow. SQL direto (sem ORM).

## Perfis

| Perfil | O que faz |
|---|---|
| **Cidadão** | Cria conta com CEP, registra ocorrências com foto tirada no local, sinaliza ocorrências de outros. |
| **Gestor** | Ligado a **uma** cidade. Vê a fila de trabalho dela, resolve, descarta, marca duplicadas e analisa sinalizações. |
| **Admin** | Cadastra cidades (contorno oficial do IBGE), promove gestores e define se a cidade exige morador. |

## Como rodar

Dentro da pasta `api`, com a venv ativa:

```
pip install -r requirements.txt
copy .env.example .env          (preencha as senhas)
python scripts/aplicar_sql.py sql/migracao_pavimentai_v2.sql sql/migracao_pavimentai_v3.sql sql/migracao_pavimentai_v4.sql sql/migracao_pavimentai_v5.sql
python -m uvicorn app.main:app --reload
```

Depois abra `http://127.0.0.1:8000/docs` (documentação e testes) e `http://127.0.0.1:8000/saude`.
Se existir a pasta `web` ao lado da `api`, o front aparece em `http://127.0.0.1:8000/web/`.

> A migração v1 (esquema inicial) foi aplicada antes dos scripts; as migrações v2 a v5 podem ser repetidas sem erro.

## Arquivo .env

| Variável | Para que serve |
|---|---|
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Conexão do banco (usuário `pavimentai_app`, com permissões mínimas). |
| `JWT_SECRET` | Chave dos tokens de login (mínimo 32 caracteres). Gere com `python -c "import secrets; print(secrets.token_hex(32))"`. |
| `DB_ADMIN_USER`, `DB_ADMIN_PASSWORD` | Usuário do banco **só do painel de admin** (criado com `scripts/criar_papel_admin_db.py`). |
| `AMBIENTE` | `dev` mostra os códigos de verificação no terminal. Em produção use `prod` e configure o envio de e-mail. |
| `CORS_ORIGENS` | Endereços do front que podem chamar a API (separados por vírgula). |
| `CEP_API_URL`, `IBGE_API_URL` | Serviços externos (ViaCEP e IBGE). Os padrões já funcionam. |
| `JANELA_FOTO_MIN`, `RAIO_FOTO_M`, `RAIO_DUPLICIDADE_M`, `LIMITE_OCORRENCIAS_HORA` | Regras antifraude, ajustáveis. |

Nunca envie o `.env` para o GitHub.

## Scripts (pasta `scripts`)

| Script | Para que serve |
|---|---|
| `aplicar_sql.py` | Aplica arquivos `.sql` no banco (pede a senha do `postgres`). |
| `baixar_limite.py` | Baixa o contorno de um município do IBGE e gera o `.sql` para cadastrá-lo. (O painel de admin faz o mesmo pela API.) |
| `definir_papel.py` | Define cidadão, gestor ou admin direto no banco. Serve para criar o **primeiro admin**. |
| `ver_usuarios.py` | Lista usuários, papéis e cidades. |
| `criar_papel_admin_db.py` | Cria o usuário `pavimentai_admin` do banco e mostra as linhas para o `.env`. |

## Rotas

**Autenticação:** `POST /auth/cadastro`, `POST /auth/verificar-email`, `POST /auth/reenviar-codigo`,
`POST /auth/login`, `PUT /auth/residencia`, `GET /auth/eu`

**Público:** `GET /areas` (cidades e contornos), `GET /cep/{cep}`, `GET /ocorrencias/mapa` (GeoJSON),
`GET /ocorrencias/{id}`, `GET /ocorrencias/{id}/fotos`, `GET /midias/{id}/arquivo`, `GET /saude`

**Cidadão:** `POST /ocorrencias`, `GET /ocorrencias/minhas`, `POST /ocorrencias/{id}/fotos`,
`POST /ocorrencias/{id}/sinalizacoes`

**Gestão** (gestor da cidade ou admin): `GET /gestao/resumo`, `GET /gestao/ocorrencias`,
`GET /gestao/ocorrencias/{id}`, `POST /gestao/ocorrencias/{id}/status`, `GET /gestao/sinalizacoes`,
`POST /gestao/sinalizacoes/{id}/analisar`

**Admin:** `GET /admin/municipios/buscar`, `GET /admin/municipios/{codigo_ibge}/previa`,
`GET`/`POST /admin/areas`, `PATCH /admin/areas/{id}`, `GET /admin/usuarios`,
`POST /admin/usuarios/{id}/papel`

## Segurança, em camadas

- **Cerca geográfica:** só se registra dentro do contorno oficial (IBGE) de uma cidade ativa.
- **Cada cidade escolhe** se exige morador (CEP → município de residência). A troca de residência é limitada a uma vez a cada 30 dias.
- **Foto na hora:** prazo de 15 min depois do registro, aparelho a menos de 100 m do local, data/GPS da foto conferidos, foto repetida ou parecida recusada, metadados (EXIF) apagados.
- **Limites:** registros por hora, sinalizações por hora, tentativas de login (5 erros travam a conta por 15 min).
- **Isolamento por cidade:** o gestor só enxerga e altera a própria cidade; a regra fica na API, não no front.
- **Privilégio mínimo no banco:** o usuário da API não cria cidades nem muda papéis; isso só o usuário de admin do banco, que também não apaga nada nem lê senhas.
- **Histórico e auditoria:** toda mudança de status e ação importante é gravada e não pode ser alterada pela API.
- Senhas com Argon2; códigos de verificação guardados só como hash.

## Ainda não implementado

Filtro de IA (YOLO) nas fotos, nível de confiança por usuário e status "em análise", novos tipos de
ocorrência (ex.: tampa de bueiro), recuperação de senha, envio real de e-mail/SMS e o front-end.
