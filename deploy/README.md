# Deploy no EC2

Cada push na `main` dispara [.github/workflows/deploy.yml](../.github/workflows/deploy.yml):

1. **test**: `pytest` (sem chamar a Tomorrow.io, tudo mockado) + `docker build`.
2. **deploy**: SSH no EC2, roda `~/notam_tw/deploy/atualizar.sh` (`git reset` para `origin/main` + `docker compose up -d --build`).
3. Confere `http://<EC2>/weather/api/health`.

O container `notam-tw` entra na rede docker do Caddy do `~/fortran`, que repassa `/weather/*` para `notam-tw:8000`.

## Primeira instalação (uma vez, no EC2)

```bash
# 1. clonar (repo privado: use uma deploy key read-only no GitHub)
git clone git@github.com:<org>/notam_tw.git ~/notam_tw
cd ~/notam_tw

# 2. segredo da API (não vai pro git)
cp .env.example .env && nano .env          # TOMORROW_API_KEY=...

# 3. nome da rede do Caddy; se não for fortran_default, coloque PROXY_NETWORK=<nome> no .env
docker network ls

# 4. subir
bash deploy/atualizar.sh
```

### Rota no Caddy (`~/fortran/Caddyfile`)

Dentro do bloco do site, junto com o `/rpl*`:

```caddyfile
redir /weather /weather/
handle_path /weather/* {
    reverse_proxy notam-tw:8000
}
```

`handle_path` tira o prefixo `/weather`, então o app continua servindo em `/`; o frontend usa caminhos relativos (`api/...`), por isso a barra final em `/weather/` é necessária (o `redir` cuida disso). Depois: `docker compose -f ~/fortran/docker-compose.yml exec caddy caddy reload --config /etc/caddy/Caddyfile` (ajuste o nome do serviço/caminho).

## Secrets do GitHub (Settings > Secrets and variables > Actions)

| Secret | Valor |
|---|---|
| `EC2_HOST` | IP ou DNS público do EC2 (sem `user@`, sem `http://`) |
| `EC2_USER` | usuário SSH (ex.: `ubuntu`, `ec2-user`) |
| `EC2_SSH_KEY` | chave **privada** usada só pelo deploy (conteúdo inteiro, com as linhas `BEGIN/END`) |
| `EC2_KNOWN_HOSTS` | saída de `ssh-keyscan -t ed25519 <EC2_HOST>` |

Se já existir uma chave de deploy para o `rpl-s3-uploader-backend` no mesmo EC2, dá para reutilizar os mesmos valores.

Gerar uma chave nova:

```bash
ssh-keygen -t ed25519 -f notam_deploy -N "" -C github-actions-notam
ssh-copy-id -i notam_deploy.pub <EC2_USER>@<EC2_HOST>   # ou cole o .pub em ~/.ssh/authorized_keys
cat notam_deploy                                          # -> EC2_SSH_KEY
ssh-keyscan -t ed25519 <EC2_HOST>                         # -> EC2_KNOWN_HOSTS
```

O security group precisa liberar a porta 22 para os runners do GitHub (ou 0.0.0.0/0 só com chave) e a 80 para quem vai usar o app.

## Diagnóstico no EC2

```bash
cd ~/notam_tw
docker compose ps
docker compose logs -f notam-tw
curl http://127.0.0.1:8000/api/health
```
