# inkdoor

[English](README.md) · **Português (Brasil)**

**Um Kindle velho na porta do escritório dizendo se dá para entrar.**

O inkdoor junta várias agendas (Outlook, Google, qualquer link ICS) e as tarefas do TickTick
numa única tela de e-ink. Quem está do lado de fora vê de longe se você está em reunião e até
quando. Você vê o dia inteiro, as folgas entre compromissos e o que falta fazer.

![Três telas do inkdoor: em reunião, livre e fora do expediente](docs/img/screens-pt-BR.png)

<sub>Telas geradas com dados fictícios (`inkdoor demo --lang pt-BR`).</sub>

## Como funciona

```
 Outlook ─┐
 Outlook ─┤   links ICS    ┌───────────────────┐   PNG 1072×1448   ┌────────┐
 Google  ─┼──────────────▶ │ inkdoor (computer)│ ────────────────▶ │ Kindle │
 TickTick ┘                └───────────────────┘   a cada 5 min    └────────┘
```

- **No computador** (`src/inkdoor`): um programa em Python lê as agendas, monta o dia e
  desenha a tela como uma imagem em 16 tons de cinza, servida na rede local.
- **No Kindle** (`kindle/`): dois *scriptlets* desligam a interface do aparelho e mostram essa
  imagem, atualizando de tempos em tempos.

Nada passa por serviços de terceiros: as agendas são lidas no seu computador e a imagem fica na
sua rede.

## O que aparece na tela

- **Status para a porta**: `EM REUNIÃO até 11:00` (fundo preto) ou `LIVRE até 16:30` (contorno).
  Reuniões emendadas viram um bloco só, então o "até" é quando você realmente sai.
- **Hoje**: compromissos de todas as agendas, folgas explícitas (`livre · 1h30`), a marca de
  *agora* e o compromisso em andamento em destaque. Os que já passaram são recolhidos.
- **Tarefas**: as de hoje e as atrasadas, com prioridade e horário.
- **Depois do expediente**, a lista passa a mostrar o dia seguinte.
- Cada agenda tem um marcador próprio (sólido, listrado, contorno), já que o e-ink não tem cor.
- **Ele não chuta.** Se o link de uma agenda falhar, os últimos dados bons do dia são reaproveitados;
  sem dado nenhum, a porta mostra `BATA ANTES` em vez de `LIVRE`.

## Começando

### 1. Computador

Requer Python 3.10+.

```sh
git clone https://github.com/frkey/inkdoor.git
cd inkdoor
pip install -e .

cp config.example.toml config.toml   # cole aqui os links das suas agendas
inkdoor check                        # confere cada link
inkdoor serve                        # gera e serve http://<ip-do-computador>:3667/kindle.png
```

No `config.toml`, defina o idioma:

```toml
[display]
language = "pt-BR"
```

Onde encontrar o link de cada agenda: [docs/pt-BR/calendar-sources.md](docs/pt-BR/calendar-sources.md).

> O `config.toml` fica fora do Git: quem tem esses links consegue ler suas agendas.

O `inkdoor serve` precisa ficar rodando para a porta atualizar. Para deixá-lo numa máquina
sempre ligada (um container no Proxmox com um comando, ou qualquer máquina Debian ou Ubuntu),
veja [docs/pt-BR/server.md](docs/pt-BR/server.md). Lá o instalador liga o **admin pela web**:
você cola os links das agendas, testa e vê uma prévia da porta no navegador, sem editar
arquivo nenhum. No seu próprio computador o admin fica desligado, a não ser que você
[ligue](docs/pt-BR/server.md#num-notebook).

### 2. Kindle

Precisa de um Kindle com jailbreak. Passo a passo: [docs/pt-BR/kindle.md](docs/pt-BR/kindle.md).
Em resumo:

1. Copie `kindle/inkdoor/` para a raiz do Kindle e `kindle/documents/*.sh` para `documents/`.
2. Em `inkdoor/config.sh`, coloque o IP do computador e `LANGUAGE="pt-BR"`.
3. Na biblioteca, abra **inkdoor - test connection** e depois **inkdoor - start display**.

## Idioma

O padrão é **inglês (en-US)**. Para português, use `language = "pt-BR"` no `config.toml` ou
passe `--lang pt-BR` em qualquer comando. Os horários seguem o padrão de cada idioma (24 horas
em pt-BR, 12 horas em en-US); para forçar, use `clock = "24h"` ou `clock = "12h"`.

## Comandos

| Comando | O que faz |
|---|---|
| `inkdoor serve` | Gera a tela a cada `refresh_minutes` e serve na porta `port`. Relê o config a cada ciclo. |
| `inkdoor render` | Gera `output/kindle.png` uma vez. |
| `inkdoor check` | Testa cada link: acesso, quantidade de compromissos, se os títulos vêm ou só "Ocupado". |
| `inkdoor demo 10:20 16:50` | Gera prévias com dados fictícios, sem precisar de agendas. |
| `inkdoor password` | Gera uma senha nova do admin, salva ao lado do `config.toml` e mostra uma única vez. Desconecta todos os navegadores. |
| `inkdoor url` | Mostra o endereço do admin para outros aparelhos da rede, ex.: `http://192.168.1.50:3667`. |

Opções gerais: `--config caminho/config.toml`, `--output pasta/`, `--lang en-US|pt-BR`.

## Configuração

Tudo fica em `config.toml`, que o [admin](docs/pt-BR/server.md#admin) edita para você (veja
os comentários em [`config.example.toml`](config.example.toml)):

- `[display]`: `language`, `timezone`, `clock`, `workday_start` / `workday_end` (expediente),
  `workdays` (dias úteis), `min_gap_minutes` (folga mínima para aparecer na lista)
- `[server]`: `port`, `refresh_minutes`
- `[[calendar]]` (uma por agenda): `name`, `style` (`solid`, `striped`, `outline`), `busy`
  (se muda o status da porta), `status_label` (a palavra grande, ex.: `"Ocupado"` para
  compromissos pessoais), `url`
- `[tasks]`: link de assinatura do TickTick e `overdue_days` (dias de atraso a mostrar)
- `[admin]`: `enabled` (o admin pela web, desligado por padrão; lido ao iniciar) e
  `allowed_hosts` (outros nomes para abrir o admin, veja
  [docs/pt-BR/server.md](docs/pt-BR/server.md#abrindo-o-admin-por-nome))

## Desenvolvimento

Veja a seção [Development](README.md#development) do README em inglês. Código, comentários,
commits e documentação técnica do projeto são em inglês; textos para o usuário ficam nos
catálogos de `src/inkdoor/locales/`.

## Licença

[MIT](LICENSE). A fonte Inter é distribuída sob a [SIL Open Font License](src/inkdoor/fonts/OFL.txt).
