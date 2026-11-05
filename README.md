# E-commerce de streetwear — Django + PostgreSQL + Railway

Loja virtual completa para uma marca brasileira de camisetas oversized nascida no Capão Redondo (Zona Sul de SP).
Nome, logotipo, cores, textos e contatos da marca são **configuráveis no painel** — o placeholder inicial é `NOME DA MARCA`.

> “DA QUEBRADA PRO MUNDO.”

## O que está pronto

| Área | Recursos |
|---|---|
| **Loja** | Homepage editorial (hero, DROP 001, mais vendidos com dados reais, coleções, manifesto, personalize, newsletter LGPD), catálogo com busca (nome/SKU/categoria/coleção), filtros (preço, tamanho, cor, coleção, modelagem, disponibilidade), ordenação, paginação, HTMX, página de produto com galeria/zoom, frente e costas, tabela de medidas, seleção cor/tamanho/modelagem com estoque por SKU, preço promocional, parcelamento informativo, frete por CEP, WhatsApp, relacionados, JSON-LD |
| **Tema** | Claro/escuro com preferência do sistema, alternância manual, persistência e transição suave (loja e painel) |
| **Conta** | Cadastro, login por e-mail com limite de tentativas, recuperação de senha, dados pessoais, endereços (ViaCEP), pedidos, rastreio, suporte, preferências de comunicação, central LGPD (exportação JSON, solicitações) |
| **Carrinho/checkout** | Carrinho persistente (sessão + usuário, mescla no login), revalidação de preço/estoque no servidor, cupons, frete, compra como visitante (link assinado do pedido + criação de conta depois), validação de CPF/CEP/telefone |
| **Pagamentos** | Mercado Pago Checkout Pro (sandbox/produção), webhook com validação de assinatura `x-signature`, consulta server-side do pagamento, idempotência, conferência de valor/moeda/modo, reconciliação, reembolso/chargeback, registro manual auditado. **Nunca** marca pago pelo retorno do navegador |
| **Estoque** | Estoque por SKU, entradas/saídas/ajustes/perdas, reservas com expiração, baixa no pagamento, devolução no cancelamento, histórico, mínimo/alertas, produtos sem giro. `SELECT … FOR UPDATE` + constraints no banco impedem estoque negativo |
| **Frete** | Arquitetura de adaptadores: retirada, frete fixo regional (UF/faixas de CEP, grátis acima de X) e Melhor Envio (cotação real). Sem credencial → só métodos válidos; **nunca inventa cotação** |
| **Personalização** | Modelo/cor/tamanho, posição da estampa com preço, upload PNG/JPEG/WebP validado pelo conteúdo real e re-codificado (remove EXIF e payloads), aviso de baixa resolução, prévia ilustrativa, texto, instruções, armazenamento privado, aprovação da equipe, carrinho e pedido |
| **Painel `/painel/`** | Dashboard com filtros de período e gráficos (Chart.js) com dados do banco, produtos (variações em grade, imagens WebP, duplicar, arquivar), preços em lote, promoções agendadas, cupons, estoque, pedidos (status, envio, rastreio, cancelamento, reconciliação), clientes (histórico, total gasto, bloqueio), personalizações, relatórios + CSV, conteúdo (marca, banners, páginas, FAQ), entregas, equipe e papéis, atendimento, LGPD, auditoria |
| **Infra** | Dockerfile multi-stage, Gunicorn, WhiteNoise (compressão + hash), S3-compatible (Railway Bucket) com URLs assinadas, health check, logs JSON, HTTPS/HSTS/cookies seguros, CSP |

## Stack

Python 3.12+ · Django 5.2 LTS · PostgreSQL 16 · Django Templates + Tailwind CSS 3 + Alpine.js + HTMX · Chart.js ·
Mercado Pago SDK · django-storages/boto3 · Gunicorn · WhiteNoise · Railway.

Fontes (Space Grotesk e Inter) e bibliotecas JS são servidas localmente (sem CDNs de terceiros — melhor para
desempenho e LGPD).

## Estrutura

```
config/              settings, urls, wsgi
apps/
  core/              utilidades, auditoria, logs JSON, uploads seguros, sitemap, health check, seed_demo
  accounts/          usuário (login por e-mail), perfil, endereços, suporte, LGPD
  catalog/           categorias, coleções, cores, tamanhos, produtos, variações, imagens, motor de preços
  inventory/         movimentações, reservas e regras de estoque (transações + locks)
  promotions/        promoções automáticas e cupons
  shipping/          métodos de entrega, cotação (Melhor Envio), envios/rastreio
  cart/              carrinho persistente e checkout
  orders/            pedidos, itens (cópia histórica), status, notificações
  payments/          Mercado Pago, webhooks, eventos, reconciliação
  personalization/   solicitações de personalização e posições de estampa
  content/           marca (singleton), banners, páginas, FAQ, newsletter
  dashboard/         painel administrativo próprio, papéis, métricas, relatórios
templates/           templates da loja, conta, e-mails e painel
static/src/input.css design system (Tailwind) → static/css/app.css
tests/               111 testes automatizados
```

## Rodando localmente

Pré-requisitos: Python 3.12+ e Node 20+ (Node só para recompilar o CSS). PostgreSQL é recomendado; sem
`DATABASE_URL` e com `DJANGO_DEBUG=1` o projeto usa SQLite apenas para desenvolvimento rápido.

```bash
python -m venv .venv
```
```bash
.venv/Scripts/activate   # Windows (Git Bash)  |  source .venv/bin/activate (Linux/macOS)
```
```bash
pip install -r requirements.txt
```
```bash
npm ci && npm run vendor && npm run build:css
```
```bash
cp .env.example .env     # edite: DJANGO_DEBUG=1, DATABASE_URL=postgres://...
```
```bash
python manage.py migrate && python manage.py seed_demo
```
```bash
python manage.py createsuperuser
```
```bash
python manage.py runserver
```

- Loja: http://localhost:8000 · Painel: http://localhost:8000/painel/ · Admin técnico: `/django-admin/` (superusuário).
- Durante o desenvolvimento do visual: `npm run watch:css`.
- `seed_demo` cria a coleção **PENSE COMO JESUS** (camisetas oversized preta e branca, P–XG), bases para personalização,
  estoques, métodos de entrega, posições de estampa, páginas legais (com campos `[PREENCHER]`), FAQ e o cupom
  `BEMVINDO10`. **Não cria pedidos nem pagamentos.** As imagens são silhuetas geradas e marcadas como “ilustrativas” —
  substitua pelas fotos reais em Painel → Produtos.

### PostgreSQL local

```bash
createdb loja && echo "DATABASE_URL=postgres://usuario:senha@localhost:5432/loja" >> .env
```

## Testes

```bash
python manage.py test tests
```

Cobrem cadastro, login (inclusive limite de tentativas e open redirect), recuperação de senha, permissões por papel,
cadastro de produtos/variações/imagens pelo painel, estoque, reservas/expiração, cupons, pedidos, webhook
(assinatura, idempotência, valor divergente, pagamento de teste em produção, reembolso), retorno do checkout,
proteção de pedidos de terceiros, uploads maliciosos, relatórios/CSV, LGPD e cabeçalhos de segurança.

O teste de **concorrência real** (8 checkouts simultâneos disputando 3 unidades) só roda em PostgreSQL — no SQLite
ele é pulado. O workflow `.github/workflows/ci.yml` executa a suíte inteira contra PostgreSQL 16.

## Mercado Pago (Checkout Pro)

1. Crie uma aplicação em https://www.mercadopago.com.br/developers/panel/app (produto “Checkout Pro”).
2. Use as **credenciais de teste** e defina `MERCADOPAGO_ENVIRONMENT=sandbox`, `MERCADOPAGO_ACCESS_TOKEN`,
   `MERCADOPAGO_PUBLIC_KEY`. Teste com usuários/cartões de teste do Mercado Pago.
3. Em *Suas integrações → Webhooks*, cadastre `https://SEU-DOMINIO/pagamentos/webhook/mercadopago/` com o evento
   **Pagamentos** e copie a assinatura secreta para `MERCADOPAGO_WEBHOOK_SECRET`.
4. `SITE_URL` precisa ser HTTPS público para `notification_url` e `auto_return` serem enviados.
5. Em produção: credenciais de produção + `MERCADOPAGO_ENVIRONMENT=production`. Pagamentos com `live_mode=false`
   recebidos em produção **não** aprovam pedidos.

Fluxo: checkout cria o pedido (estoque reservado) → preferência → checkout oficial → webhook/retorno → o servidor
consulta `GET /v1/payments/{id}` → confere referência, valor e moeda → pedido pago e estoque baixado.
Sem credenciais, o botão de pagamento fica indisponível com instruções (em dev, `ALLOW_ORDERS_WITHOUT_GATEWAY=1`
registra pedidos “aguardando pagamento”, nunca pagos).

Rotinas recomendadas (Railway Cron, ver abaixo):
`python manage.py release_expired_reservations` (a cada 10 min) e `python manage.py reconcile_payments` (a cada hora).

## Armazenamento de arquivos

O disco do container no Railway é efêmero. Configure um bucket S3-compatible:

- **Railway Bucket**: crie o bucket no projeto e copie endpoint, nome, chaves e região para as variáveis `S3_*`.
  Buckets do Railway são privados: imagens de produtos são entregues com URLs assinadas de longa duração
  (`S3_PUBLIC_MEDIA_SIGNED=1`).
- **Cloudflare R2 / AWS S3**: mesmas variáveis; com bucket/CDN público, use `S3_CUSTOM_DOMAIN` e
  `S3_PUBLIC_MEDIA_SIGNED=0`.
- Artes de personalização ficam no prefixo `private/` e só são entregues pela rota autenticada
  `/personalize/<id>/arte/` (dono ou equipe), via URL assinada de 5 minutos.
- Alternativa sem S3: Railway Volume montado em `MEDIA_ROOT` + `SERVE_MEDIA_FROM_DISK=1` (1 réplica apenas).

## Deploy no Railway

1. Suba o repositório para o GitHub e crie um projeto no Railway a partir dele (o `railway.json` usa o `Dockerfile`).
2. Adicione **PostgreSQL** ao projeto. No serviço web, crie `DATABASE_URL=${{Postgres.DATABASE_URL}}`.
3. Adicione um **Bucket** e preencha as variáveis `S3_*`.
4. Cadastre as variáveis do `.env.example` (no mínimo `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`,
   `DJANGO_CSRF_TRUSTED_ORIGINS`, `SITE_URL`, e-mail SMTP e Mercado Pago).
5. Deploy: o build compila Tailwind e roda `collectstatic`; ao iniciar, `scripts/start.sh` executa `migrate` e
   `setup_roles` e só então sobe o Gunicorn. O health check `/healthz/` responde 503 se o banco estiver
   inacessível ou houver migração pendente — assim um deploy com banco desatualizado não entra no ar.
   Se o serviço tiver um *Custom Start Command* ou *Pre-deploy Command* definido no painel do Railway, remova-o
   para usar o do `railway.json`.
6. Crie o primeiro administrador — escolha uma opção:
   - **Por variáveis (sem terminal):** cadastre `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD` e
     (opcional) `DJANGO_SUPERUSER_FULL_NAME` no serviço web e faça o deploy. O `start.sh` cria o superusuário se
     ele ainda não existir; nunca altera um usuário existente. Depois do primeiro acesso, **apague
     `DJANGO_SUPERUSER_PASSWORD`** das variáveis.
   - **Pelo terminal do container:** `railway ssh` e depois `python manage.py createsuperuser`.
     (Não use `railway run`: ele executa no seu computador, que não acessa o endereço interno do banco.)
   Acesse `/conta/entrar/` com o e-mail e a senha; o painel fica em `/painel/`.
7. **Domínio próprio**: Settings → Networking → Custom Domain; crie o CNAME indicado no seu DNS e inclua o domínio em
   `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` e `SITE_URL`. HTTPS é emitido automaticamente.
8. **Cron**: crie um segundo serviço do mesmo repositório com *Cron Schedule* `*/10 * * * *` e start command
   `python manage.py release_expired_reservations` (e outro, horário, com `reconcile_payments`).
9. Mais de uma réplica? Configure `REDIS_URL` para compartilhar cache e limites de tentativas.

### Backup do PostgreSQL

- Ative os backups do serviço Postgres no Railway (Backups → agenda diária/semanal) e teste uma restauração.
- Backup lógico adicional (fora do Railway), por exemplo semanal:
  `pg_dump "$DATABASE_URL" --format=custom --no-owner -f backup-$(date +%F).dump` e envie para outro bucket.
- Restauração: `pg_restore --clean --no-owner -d "$DATABASE_URL" backup.dump`.

## Papéis da equipe

`python manage.py setup_roles` cria: **Administrador geral**, **Gestor comercial**, **Estoquista**, **Atendimento**
(cliente = usuário sem papel). As permissões são verificadas no servidor em cada ação. Gerencie em Painel → Equipe.

## Solução de problemas

| Sintoma | Causa provável |
|---|---|
| `DJANGO_SECRET_KEY é obrigatória` | Variável ausente com `DJANGO_DEBUG=0` |
| 400 Bad Request | Domínio fora de `DJANGO_ALLOWED_HOSTS` |
| 403 CSRF em formulários | Domínio fora de `DJANGO_CSRF_TRUSTED_ORIGINS` (com `https://`) |
| Imagens somem após deploy | Falta configurar o bucket S3 (disco efêmero) |
| Webhook retorna 401 | `MERCADOPAGO_WEBHOOK_SECRET` diferente do painel do Mercado Pago |
| Pedido pago ainda “aguardando” | Webhook não chegou: use “Consultar no Mercado Pago” no pedido ou `reconcile_payments` |
| Sem opções de frete | Nenhum método ativo atende o CEP; Melhor Envio exige `MELHORENVIO_TOKEN` e `STORE_ORIGIN_ZIPCODE` |
| CSS sem estilo | Rode `npm run build:css` (local) — no Docker é automático |

Veja também [DESIGN.md](DESIGN.md) e o [checklist de publicação](PUBLICACAO.md).
