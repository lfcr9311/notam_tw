# Deploy no EC2 (`/weather`)

Roda no mesmo EC2 do RPL (`ec2-3-137-219-87.us-east-2.compute.amazonaws.com`). O container
`notam-tw` entra na rede do Caddy do `~/fortran` (`fortran_default`), e o Caddy repassa
`/weather/*` para `notam-tw:8000` tirando o prefixo (rota em `~/fortran/deploy/Caddyfile`).

A cada push na `master`, `.github/workflows/deploy.yml` roda os testes (mockados, sem gastar
request da Tomorrow.io), entra no EC2 por SSH e roda `deploy/atualizar.sh`: `git reset` para
`origin/master`, `docker compose up -d --build`, conferência de `/weather/api/health`.

## Uma vez no seu computador

Chave só para o deploy, limitada a rodar o `atualizar.sh` deste repositório
(já criada em `~/.ssh/gh_deploy_notam_tw`):

```bash
H=ec2-3-137-219-87.us-east-2.compute.amazonaws.com
echo "command=\"bash ~/notam_tw/deploy/atualizar.sh\",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty $(cat ~/.ssh/gh_deploy_notam_tw.pub)" \
  | ssh -i ~/Downloads/SSH.pem -o IdentitiesOnly=yes ubuntu@$H 'cat >> ~/.ssh/authorized_keys'
```

## Uma vez no EC2

```bash
git clone https://github.com/lfcr9311/notam_tw.git ~/notam_tw
```

Copie o `.env` com a `TOMORROW_API_KEY` (não vai pro git), do seu computador:

```bash
scp -i ~/Downloads/SSH.pem -o IdentitiesOnly=yes .env ubuntu@$H:~/notam_tw/.env
```

Depois, no EC2: `bash ~/notam_tw/deploy/atualizar.sh`.

## Uma vez no GitHub: secrets (já cadastrados)

```bash
R=lfcr9311/notam_tw
gh secret set EC2_HOST -R $R -b "$H"
gh secret set EC2_USER -R $R -b "ubuntu"
gh secret set EC2_SSH_KEY -R $R < ~/.ssh/gh_deploy_notam_tw
ssh-keyscan -t ed25519 $H | gh secret set EC2_KNOWN_HOSTS -R $R
```

## Dia a dia

No EC2, em `~/notam_tw`:
- `docker compose logs -f notam-tw`: log do servidor
- `curl http://127.0.0.1:8000/api/health`: o app, sem passar pelo Caddy
- `bash deploy/atualizar.sh`: o mesmo deploy, rodado à mão
- mudou o `.env`: `docker compose up -d --force-recreate`
