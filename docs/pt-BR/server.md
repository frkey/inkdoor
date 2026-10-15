# Rodando o inkdoor num servidor de casa

[English](../server.md) · **Português (Brasil)**

O `inkdoor serve` precisa ficar rodando o tempo todo: quando ele para, o Kindle para de
atualizar. Um notebook que dorme à noite não é um bom lugar para ele. Um servidor de casa é
melhor, e o inkdoor é leve: um processo Python pequeno, que usa menos de 100 MB de RAM e cerca
de 1 GB de disco, já contando o sistema operacional.

- **Proxmox VE**: um comando cria um container com tudo pronto. [Ir para lá](#proxmox-ve).
- **Qualquer máquina Debian ou Ubuntu** (uma VM, um mini PC, um Raspberry Pi com sistema
  64 bits): [use o instalador](#debian-ou-ubuntu).

Nos dois casos, o resultado é o mesmo:

| Caminho | O que é |
|---|---|
| `/etc/inkdoor/config.toml` | sua config, legível só pelo root e pelo usuário `inkdoor` |
| `/opt/inkdoor` | o código e o ambiente Python |
| `/var/lib/inkdoor/kindle.png` | a tela gerada |
| `inkdoor.service` | o serviço do systemd, que sobe no boot e reinicia se cair |
| `/usr/local/bin/inkdoor` | roda o inkdoor com essa config: `inkdoor check`, `inkdoor render` |

## Proxmox VE

O `deploy/proxmox/create-lxc.sh` roda no host do Proxmox. Ele baixa o template mais novo do
Debian (o 13, ou o 12 em versões do Proxmox que ainda não aceitam o 13), cria um container sem privilégios (1 core, 512 MB de RAM, 4 GB de disco, ligado no
boot) e instala o inkdoor nele.

1. Abra um terminal no host do Proxmox: na interface web, selecione o nó e clique em
   **Shell** (ou entre por SSH como root).
2. Baixe o script e, se quiser, leia antes de rodar:

   ```sh
   curl -fsSLO https://raw.githubusercontent.com/frkey/inkdoor/master/deploy/proxmox/create-lxc.sh
   ```

3. Rode:

   ```sh
   bash create-lxc.sh --lang pt-BR
   ```

   Para levar o `config.toml` que você já tem, copie-o antes para o host (por exemplo
   `scp config.toml root@<ip-do-proxmox>:`) e acrescente `--config config.toml`.

4. No fim, o script mostra o ID e o IP do container.
   - **Se você passou `--config`**, o serviço já está rodando.
   - **Se não**, termine a configuração dentro do container:

     ```sh
     pct enter <id>
     nano /etc/inkdoor/config.toml   # cole os links das agendas (docs/pt-BR/calendar-sources.md)
     inkdoor check                   # testa cada link
     systemctl start inkdoor
     ```

5. No Kindle, coloque `URL="http://<ip-do-container>:8000/kindle.png"` em
   `inkdoor/config.sh` ([configurando o Kindle](kindle.md)).

### Opções

| Opção | Padrão | |
|---|---|---|
| `--config ARQUIVO` | | `config.toml` a copiar para o container |
| `--lang en-US\|pt-BR` | idioma do sistema, senão `en-US` | idioma da tela numa config nova e das mensagens do script |
| `--ip dhcp\|CIDR` | `dhcp` | um endereço fixo, por exemplo `192.168.1.50/24` |
| `--gateway IP` | | seu roteador; obrigatório com `--ip` fixo |
| `--ctid N` | próximo ID livre | |
| `--hostname NOME` | `inkdoor` | |
| `--bridge NOME` | `vmbr0` | |
| `--storage NOME` | `local-lvm` | onde fica o disco do container |
| `--template-storage NOME` | `local` | onde fica o template do Debian |
| `--disk GB` | `4` | dá para aumentar depois com `pct resize <id> rootfs +1G` |
| `--memory MB` | `512` | |
| `--ref BRANCH_OU_TAG` | `master` | versão do inkdoor a instalar |

O Kindle precisa achar o servidor sempre no mesmo endereço. Use um `--ip` fixo ou reserve o
endereço do container no roteador ("reserva de DHCP").

### No dia a dia

| Tarefa | Comando no host do Proxmox |
|---|---|
| Atualizar o inkdoor | `pct exec <id> -- bash /opt/inkdoor/deploy/install.sh` |
| Acompanhar o log | `pct exec <id> -- journalctl -u inkdoor -f` |
| Testar os links das agendas | `pct exec <id> -- inkdoor check` |
| Editar a config | `pct enter <id>` e depois `nano /etc/inkdoor/config.toml` |

Mudanças na config valem a partir da próxima atualização da tela; só uma `port` nova precisa de
`systemctl restart inkdoor`.

### Criando o container na mão

Se preferir criar o container pela interface web, deixe-o **sem privilégios** (unprivileged) e
com o recurso **nesting** ligado (os dois já vêm assim por padrão). O serviço roda num sandbox
do systemd, que não sobe sem nesting (status `226/NAMESPACE`). Depois, siga a próxima seção
dentro do container.

## Debian ou Ubuntu

O `deploy/install.sh` funciona no Debian 12 ou mais novo e no Ubuntu 22.04 ou mais novo, com
systemd. Como root:

```sh
curl -fsSLO https://raw.githubusercontent.com/frkey/inkdoor/master/deploy/install.sh
bash install.sh --lang pt-BR
```

Ele instala o Python e o git pelo apt, baixa o inkdoor em `/opt/inkdoor` e cria o usuário
`inkdoor` e o serviço. Na primeira vez, cria o `/etc/inkdoor/config.toml` a partir do exemplo,
com o fuso horário da máquina e o `--lang` escolhido. O serviço só sobe quando a config tem pelo
menos um link: preencha, rode `inkdoor check` e depois `systemctl start inkdoor`.

Para atualizar, rode `bash /opt/inkdoor/deploy/install.sh`. Ele baixa a versão nova do mesmo
repositório e branch (`--ref`) de antes e reinicia o serviço. Sua config nunca é sobrescrita.

Opções: `--lang en-US|pt-BR`, `--timezone Area/Cidade` (para uma config nova),
`--ref BRANCH_OU_TAG`.

## Segurança

- **Deixe tudo na rede local.** Nunca abra a porta no roteador (port forward): a imagem mostra a
  sua agenda. Se o servidor tem firewall, libere a porta só para a sua rede ou só para o IP do
  Kindle.
- O servidor HTTP só responde `/kindle.png`, e o serviço roda com um usuário sem privilégios,
  num sandbox do systemd que só pode gravar em `/var/lib/inkdoor`.
- O `config.toml` guarda links secretos: quem tem esses links consegue ler suas agendas.
