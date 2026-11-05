# Design system

Streetwear editorial: tipografia grande, layouts assimétricos, cantos retos, poucas cores usadas com intenção,
textura sutil de cartaz urbano. Fonte do sistema: `static/src/input.css` + `tailwind.config.js`.

## Identidade

- **Tom**: direto, autêntico, orgulhoso da origem. Sem estereótipos de criminalidade ou pobreza.
- **Motivos gráficos**: cantoneiras (`.brackets`), grade fina (`.grid-texture`), granulado (`.grain`),
  marca-texto lima (`.marker`), etiquetas estilo lambe-lambe (`.tag`), faixas em marquee.
- **Nada fixo no código**: nome, logo (claro/escuro), favicon, imagem OG, cores de destaque, slogan, textos
  institucionais e redes sociais vêm de `BrandSettings` (Painel → Marca). As cores de destaque viram variáveis CSS.

## Tipografia

| Uso | Fonte | Classe |
|---|---|---|
| Títulos, botões, etiquetas | Space Grotesk Variable (300–700) | `font-display`, `.display`, `.eyebrow` |
| Texto e formulários | Inter Variable | `font-sans` (padrão) |
| Dados técnicos (SKU, coordenadas) | monoespaçada do sistema | `.kicker`, `font-mono` |

Escala display fluida: `text-display-xl` (hero), `text-display-lg` (títulos de página), `text-display-md` (seções).
Fontes auto-hospedadas (woff2 latin + latin-ext), `font-display: swap` e `preload` das principais.

## Paleta (tokens RGB em `:root` / `.dark`)

| Token | Claro | Escuro |
|---|---|---|
| `bg` | `#F7F5F0` | `#101010` |
| `surface` | `#FFFFFF` | `#1B1B1B` |
| `fg` | `#171717` | `#F5F5F5` |
| `line` | `#DEDEDA` | `#333333` |
| `muted` | `#5C5C58` | `#A8A8A2` |

Destaques: **lima** `#C7FF3D` (CTA principal, marca-texto, seleção), **laranja** `#FF623B` (promoções, alertas),
**azul elétrico** `#355CFF` (links informativos, foco no tema claro).

Regras de contraste:
- Lima nunca é usado como cor de texto sobre fundo claro; sempre como **fundo** com texto `#171717`.
- Laranja como texto só em tamanhos grandes/negrito; em textos pequenos use etiqueta (`.tag-orange`).
- Hero, coleções e telas de login usam o fundo escuro editorial (`#101010`) em ambos os temas.

## Componentes

`.btn` + `.btn-primary` (lima) · `.btn-dark` · `.btn-outline` · `.btn-ghost` · `.btn-danger` · `.btn-sm` · `.btn-block`
— microinteração de deslocamento com sombra dura e brilho deslizante.
`.input`, `.label`, `.help`, `.error`, `.checkbox` · `.chip` / `.chip-active` / `.chip-disabled` (tamanhos, filtros)
· `.tag` / `.tag-lime` / `.tag-orange` / `.tag-outline` · `.badge-*` (status) · `.panel` · `.table-clean`
· `.product-media` (proporção 4:5, troca para a segunda foto no hover) · `.toast` · `.link-slide` · `.prose-store`.
Partials: `catalog/_card.html`, `partials/field.html`, `partials/header.html`, `partials/footer.html`.

## Breakpoints (mobile-first)

`xs 400` · `sm 640` · `md 768` · `lg 1024` (menu completo, layout em colunas) · `xl 1280` · `2xl 1536`.
Container `.shell`: máx. 1440 px, gutters 16/24/40 px. Header sticky de 60 px (mobile) / 72 px (desktop).
No mobile: menu em gaveta, filtros em gaveta, carrossel com scroll-snap, CTAs de largura total.

## Claro/escuro

- Script inline no `<head>` aplica a classe `dark` antes da pintura (sem flash).
- Preferência: `system` (padrão, segue `prefers-color-scheme`), `light` ou `dark`, salva em `localStorage`.
- Alternância adiciona `.theme-transition` por 400 ms para transição suave; o painel usa o mesmo mecanismo.
- Gráficos do painel releem as cores ao trocar de tema.

## Imagens

- Produto: proporção 4:5, mínimo 1600 px no lado maior, fundo neutro; envie frente e costas (vista “Costas” para a
  arte principal). Uploads são convertidos para WebP (1600 px) + miniatura (640 px) com `width/height` (sem CLS).
- Marque “imagem ilustrativa” em mockups — a loja exibe o aviso.
- Lazy loading em tudo abaixo da dobra; `fetchpriority="high"` na imagem principal.
- Nunca recrie a arte da coleção em CSS: use as fotos/mockups reais.

## Acessibilidade (meta WCAG 2.2 AA)

Link “pular para o conteúdo”, foco visível (azul/lima), alvos de toque ≥ 40 px, rótulos em todos os campos,
`aria-live` para carrinho/frete/filtros, `aria-current` na navegação, `aria-pressed` em seletores, diálogos com
`role="dialog"` e fechamento por Esc, `prefers-reduced-motion` respeitado, contraste verificado nas combinações acima.
