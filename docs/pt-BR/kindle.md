# Preparando o Kindle

[English](../kindle.md) · **Português (Brasil)**

O inkdoor roda em Kindles com jailbreak. O lado do Kindle é simples: dois scriptlets que
desligam a interface do aparelho e mostram a imagem gerada pelo computador.

## 1. Jailbreak

Siga o guia atualizado do [Kindle Modding](https://kindlemodding.org/jailbreaking/). O método
depende do modelo e da versão do firmware (Configurações → Opções do dispositivo → Informações
do dispositivo). Os jailbreaks recentes já instalam o suporte a **scriptlets**: arquivos `.sh`
na pasta `documents` que aparecem na biblioteca e rodam quando você toca neles.

Antes de começar, deixe o Kindle em **modo avião** para ele não atualizar o firmware.

## 2. Instalação

Com o Kindle ligado no computador pelo USB:

```
Kindle/
├── documents/
│   ├── inkdoor-start.sh       ← de kindle/documents/
│   └── inkdoor-test.sh        ← de kindle/documents/
└── inkdoor/                   ← a pasta kindle/inkdoor/ inteira
    ├── common.sh
    ├── config.sh
    └── loop.sh
```

Edite `inkdoor/config.sh`:

```sh
URL="http://192.168.0.10:8000/kindle.png"   # IP do computador que roda o "inkdoor serve"
INTERVAL=300                                # segundos entre atualizações
FULL_REFRESH_EVERY=6                        # a cada N atualizações, uma completa (pisca e limpa fantasmas)
LANGUAGE="pt-BR"                            # mensagens no Kindle: en-US ou pt-BR
```

O arquivo pode ser editado no Windows: as quebras de linha são corrigidas automaticamente.

## 3. Uso

Ejete o Kindle. Na biblioteca aparecem:

- **inkdoor - test connection**: liga o Wi-Fi, baixa a imagem uma vez e diz se deu certo.
  Não muda nada no Kindle.
- **inkdoor - start display**: desliga a interface do Kindle e passa a mostrar a agenda.

**Para voltar ao Kindle normal, reinicie o aparelho** (segure o botão liga/desliga). O painel
não inicia sozinho depois de reiniciar.

## Dicas

- **Energia**: o painel mantém o Wi-Fi ligado e não usa hibernação, então o ideal é deixar o
  Kindle no carregador. Um cabo USB fino passa bem pelo batente da porta.
- **IP fixo**: reserve um IP para o computador no roteador, senão o endereço muda e o painel
  para de atualizar.
- **Sem conexão**: depois de 3 falhas seguidas, aparece "sem conexao com o PC" no canto da tela.
  O histórico fica em `inkdoor/log.txt`.
