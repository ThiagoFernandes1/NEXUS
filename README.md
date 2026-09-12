# 🛰️ NEXUS — Painel de Dados em Tempo Real

Dashboard web profissional em Python que agrega **cinco APIs públicas reais** em uma única
interface animada, com streaming ao vivo, cache persistente, histórico em banco de dados
e testes automatizados.

Nenhuma chave de API é necessária — todos os serviços usados são abertos.

---

## ✨ O que ele faz

| Painel | Fonte de dados | Atualização |
|---|---|---|
| **Clima** — temperatura, sensação, umidade, vento, pressão e previsão de 5 dias | [Open-Meteo](https://open-meteo.com) | 10 min |
| **Criptomoedas** — BTC, ETH, SOL, ADA, DOGE em USD e BRL, variação 24 h | [CoinGecko](https://www.coingecko.com/api) | 1 min |
| **Câmbio** — USD, EUR, GBP e BTC contra o Real | [AwesomeAPI](https://docs.awesomeapi.com.br) | 2 min |
| **Notícias espaciais** — manchetes com imagem | [Spaceflight News](https://spaceflightnewsapi.net) | 15 min |
| **Estação Espacial** — posição orbital com rastro no mapa | [Open-Notify](http://open-notify.org) | 5 s |

### Recursos técnicos

- **Streaming em tempo real (SSE)** — o navegador recebe atualizações sem recarregar a página.
- **Cache persistente em SQLite** — primeira carga ~900 ms, seguintes ~13 ms.
- **Degradação suave** — se uma API cair, o painel serve o último dado válido e avisa
  com o selo `obsoleto`, em vez de quebrar.
- **Retry com backoff exponencial** — 3 tentativas antes de desistir.
- **Busca de cidade com autocomplete** — digite qualquer cidade do mundo.
- **Gráfico histórico interativo** — clique em qualquer moeda para trocar a série.
- **Tema claro/escuro** com preferência salva no navegador.
- **Canvas puro** — estrelas animadas, mapa da ISS e gráficos desenhados à mão,
  sem nenhuma biblioteca externa. Funciona offline depois de carregado.
- **Acessibilidade** — respeita `prefers-reduced-motion`.

---

## 🚀 Como usar

```bash
# 1. Instale as dependências
pip install -r requirements.txt

# 2. (Opcional, recomendado) Popule o histórico com 7 dias reais de mercado
python -m app.seed 7

# 3. Inicie
python run.py
```

O navegador abre sozinho em <http://127.0.0.1:5000>.

### Opções da linha de comando

```bash
python run.py --port 8080      # muda a porta
python run.py --no-browser     # não abre o navegador
python run.py --debug          # modo de depuração
```

### Configuração por variáveis de ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `NEXUS_PORT` | `5000` | porta do servidor |
| `NEXUS_CITY` | `São Paulo` | cidade inicial do painel de clima |
| `NEXUS_LAT` / `NEXUS_LON` | `-23.5505` / `-46.6333` | coordenadas iniciais |
| `NEXUS_DB` | `sqlite:///data/nexus.db` | banco de dados |
| `NEXUS_DEBUG` | `0` | `1` ativa o modo de depuração |

---

## 🔌 API REST

O painel é só um cliente — todo o backend é acessível como API.

| Rota | Descrição |
|---|---|
| `GET /api/snapshot` | todos os serviços de uma vez (aceita `?only=crypto,forex`) |
| `GET /api/service/<nome>` | um serviço específico |
| `GET /api/weather?lat=&lon=&city=` | clima em coordenadas arbitrárias |
| `GET /api/geocode?q=` | busca de cidades |
| `GET /api/history/<série>` | série temporal, ex.: `crypto.bitcoin` |
| `GET /api/events` | log de atividade do sistema |
| `GET /api/health` | verificação de saúde (uptime, latência, serviços) |
| `GET /api/stream` | fluxo Server-Sent Events |
| `POST /api/maintenance/prune` | limpa dados com mais de 48 h |

Exemplo:

```bash
curl http://127.0.0.1:5000/api/health
curl "http://127.0.0.1:5000/api/weather?lat=-8.05&lon=-34.9&city=Recife"
```

---

## 🧪 Testes

```bash
python -m pytest tests/ -q
```

19 testes cobrindo cache, expiração, fallback para dado obsoleto, retry, rotas HTTP,
validação de parâmetros e transformação de dados. As chamadas externas são simuladas,
então a suíte roda **offline** e sem consumir cota das APIs.

---

## 📁 Estrutura

```
NexusDashboard/
├── run.py                  ponto de entrada
├── requirements.txt
├── app/
│   ├── config.py           configurações (env vars + defaults)
│   ├── models.py           ORM: cache, métricas e eventos
│   ├── services.py         conectores de API, cache e retry
│   ├── server.py           rotas Flask + streaming SSE
│   ├── seed.py             importa histórico real de mercado
│   ├── templates/
│   │   └── index.html
│   └── static/
│       ├── css/style.css
│       └── js/app.js       canvas, gráficos e SSE (sem dependências)
├── tests/
│   └── test_nexus.py
└── data/
    └── nexus.db            criado automaticamente
```

---

## 🏗️ Como funciona

```
Navegador  ──SSE──►  Flask  ──►  camada de cache (SQLite)
    ▲                             │ (se expirado)
    │                             ▼
    └──── JSON ────────────  APIs públicas  (retry + backoff)
                                  │
                                  ▼
                         histórico de métricas → gráficos
```

Cada serviço tem seu próprio TTL. Uma requisição só sai para a internet quando o cache
expira; quando a API falha, o dado anterior continua sendo servido e marcado como obsoleto.

---

## 📝 Licença

MIT — use, modifique e distribua livremente.
