# Checklist de publicação real

Itens que dependem de contas, credenciais ou decisões do negócio — o código já está preparado para cada um.

## Marca e conteúdo
- [ ] Definir o nome da marca e enviar logotipo (claro e escuro), favicon e imagem de compartilhamento (Painel → Marca)
- [ ] Fotos reais dos produtos (frente, costas, detalhe, modelo) substituindo as imagens ilustrativas do `seed_demo`
- [ ] Revisar preços, custos, estoques e tabelas de medidas reais
- [ ] Banner do hero (Painel → Conteúdo → Banners) e capa das coleções
- [ ] Textos “Sobre” e manifesto; FAQ
- [ ] Redes sociais e WhatsApp comercial

## Jurídico / comércio eletrônico (Decreto 7.962/2013, CDC, LGPD)
- [ ] Razão social, CNPJ e endereço em Painel → Marca (aparecem no rodapé)
- [ ] Revisar com profissional e remover os `[PREENCHER]` de: Política de privacidade, Termos de uso, Trocas e
      devoluções, Política de entrega
- [ ] Indicar o encarregado de dados (DPO) e canal de atendimento LGPD
- [ ] Definir regra de troca de produtos personalizados
- [ ] Emissão de nota fiscal (integração com emissor/ERP não incluída)

## Infraestrutura (Railway)
- [ ] Projeto criado a partir do GitHub, PostgreSQL adicionado e `DATABASE_URL` referenciada
- [ ] Bucket S3 configurado (`S3_*`) — sem isso, uploads se perdem a cada deploy
- [ ] `DJANGO_SECRET_KEY` forte, `DJANGO_DEBUG=0`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `SITE_URL`
- [ ] Domínio próprio + DNS (CNAME) + HTTPS ativo
- [ ] Backups automáticos do Postgres ligados **e uma restauração testada**
- [ ] Serviços cron: `release_expired_reservations` (10 min) e `reconcile_payments` (1 h)
- [ ] Superusuário criado; equipe cadastrada com papéis mínimos necessários
- [ ] `REDIS_URL` se houver mais de uma réplica

## E-mail
- [ ] Provedor SMTP transacional (ex.: Amazon SES, Resend, Brevo) com domínio verificado (SPF, DKIM, DMARC)
- [ ] `DEFAULT_FROM_EMAIL` no domínio da loja; testar recuperação de senha e e-mail de pedido

## Pagamentos (Mercado Pago)
- [ ] Conta vendedor verificada, meios habilitados (Pix, cartão, parcelamento desejado)
- [ ] Testes em sandbox: aprovado, recusado, pendente (Pix não pago), cancelado e estorno
- [ ] Webhook cadastrado com a URL de produção e `MERCADOPAGO_WEBHOOK_SECRET` configurado
- [ ] Trocar para credenciais de produção + `MERCADOPAGO_ENVIRONMENT=production`
- [ ] Compra real de valor baixo de ponta a ponta + estorno pelo painel do Mercado Pago
- [ ] Conferir `MERCADOPAGO_MAX_INSTALLMENTS` e o texto de parcelamento (Painel → Marca → Vendas)

## Frete
- [ ] `STORE_ORIGIN_ZIPCODE` com o CEP de postagem
- [ ] Endereço/horário da retirada no local e regras do frete regional (Painel → Entregas)
- [ ] Conta Melhor Envio, token de produção em `MELHORENVIO_TOKEN`, `MELHORENVIO_USER_AGENT` com e-mail de contato
- [ ] Pesos e dimensões reais das embalagens em cada produto
- [ ] Testar cotação para CEPs de diferentes regiões

## Testes finais
- [ ] `python manage.py test tests` em PostgreSQL (inclui o teste de concorrência) — o CI do GitHub já faz isso
- [ ] Navegação completa no celular (Android e iPhone) e desktop, temas claro e escuro
- [ ] Compra como visitante e como cliente logado; criação de conta após a compra
- [ ] Personalização: envio, aprovação, compra
- [ ] Painel: cadastrar produto, variações, imagens, alterar preço, criar promoção, atualizar pedido, relatórios
- [ ] Lighthouse (performance, acessibilidade, SEO) nas páginas Home, Produto e Checkout
- [ ] Enviar `sitemap.xml` ao Google Search Console
