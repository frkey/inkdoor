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

### Pelo Kindle, com o KPM (sem cabo)

Os jailbreaks recentes já vêm com o **KPM**, o gerenciador de pacotes do Kindle, e o seu servidor
inkdoor funciona como um repositório do KPM. No Kindle, toque na barra de busca e digite cada
linha, apertando Enter depois de cada uma (a página **Início** do admin mostra as linhas com o
endereço do seu servidor):

```
;kpm add-repo http://192.168.1.50:3667/kpm.json
;kpm update
;kpm install inkdoor
```

O pacote já vem apontando para o seu servidor e no idioma do admin. Para atualizar o Kindle
depois de atualizar o servidor, digite `;kpm update` e depois `;kpm upgrade`: as configurações do
seu `config.sh` são mantidas. Para remover o inkdoor, digite `;kpm uninstall inkdoor`.

Se o endereço do servidor mudar, instale de novo a partir do novo: `;kpm uninstall inkdoor` e
`;kpm remove-repo inkdoor`, depois as três linhas acima com o endereço novo (isso volta o
`config.sh` ao padrão; reservar o endereço do servidor no roteador evita isso).

### Sem o KPM: baixe os arquivos no admin

Na página **Início** do admin, aperte **Baixar os arquivos do Kindle**. O `.zip` já vem com o
endereço do seu servidor e o seu idioma no `inkdoor/config.sh`. Com o Kindle ligado no USB:

1. Descompacte.
2. Copie a pasta `inkdoor` para a raiz do Kindle, ao lado da pasta `documents`.
3. Copie os dois arquivos de `scriptlets` para a pasta `documents` do Kindle. Copie os arquivos,
   não a pasta: substituir `documents` apagaria os seus livros.

O `README.txt` dentro do zip tem os mesmos passos.

### À mão

A partir de uma cópia deste repositório, com o Kindle ligado no USB:

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
URL="http://192.168.0.10:3667/kindle.png"   # IP do computador que roda o "inkdoor serve"
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
  para de atualizar. Um servidor de casa evita isso e nunca dorme ([server.md](server.md)).
- **Uma instância só**: tocar duas vezes em "start display" não inicia dois painéis.
- **Sem conexão**: depois de 3 falhas seguidas, aparece "sem conexao com o PC" no canto da tela.
  O histórico fica em `inkdoor/log.txt`, e a
  [Solução de problemas](troubleshooting.md#no-kindle) explica cada mensagem.
