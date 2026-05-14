# Deploy no Azure App Service — Azure Pricing MCP Server

Guia passo a passo para publicar o `azure_pricing_mcp_server.py` em **Azure App Service for Linux** usando Python 3.11 nativo (sem Docker) e CI/CD via **GitHub Actions**, com restrição de rede por IP.

---

## 1. Visão geral da arquitetura

```
GitHub (push em main)
        │
        ▼
GitHub Actions  ──►  azure/webapps-deploy@v3  ──►  Azure App Service (Linux/Python 3.11)
                                                          │
                                                          ├── startup.sh → gunicorn + UvicornWorker
                                                          ├── App Settings (substituem .env)
                                                          └── Access Restrictions (IP allow-list)
                                                                    │
                                                                    ▼
                                                       https://<app>.azurewebsites.net/sse
                                                       https://<app>.azurewebsites.net/tools
```

A aplicação é ASGI (Starlette) e é servida em produção por `gunicorn` com o worker `uvicorn.workers.UvicornWorker`. O `__main__` do arquivo Python só é usado em desenvolvimento; no App Service o startup é controlado pelo `startup.sh`.

---

## 2. Arquivos criados neste repositório

| Arquivo | Propósito |
|---|---|
| `startup.sh` | Comando de inicialização que o App Service executa para subir o gunicorn na porta `$PORT`. |
| `.deployment` | Diz ao Oryx (builder do App Service) para instalar `requirements.txt` no deploy. |
| `.github/workflows/azure-deploy.yml` | Pipeline de CI/CD que empacota o repo em `release.zip` e publica via `azure/webapps-deploy@v3`. |
| `requirements.txt` | Agora inclui `gunicorn` e `pydantic-settings`. |

---

## 3. Pré-requisitos

- Conta Azure com permissão para criar **Resource Group**, **App Service Plan** e **Web App**.
- `az CLI` versão recente (`az --version` ≥ 2.55).
- Repositório no GitHub (para o workflow funcionar).
- Lista de IPs públicos que poderão acessar o endpoint (escritório, VPN corporativa, IP do MCP client).

---

## 4. Provisionar a infraestrutura (uma vez)

Execute em um terminal autenticado (`az login`). Ajuste os nomes — eles precisam ser únicos no Azure.

```bash
# Variáveis
RG="rg-mcp-azure-pricing"
LOCATION="brazilsouth"          # ou eastus, westeurope, etc.
PLAN="asp-mcp-azure-pricing"
APP="mcp-azure-pricing"          # precisa ser globalmente único
SKU="B1"                         # B1 é suficiente; P1V3 se precisar de escala/SLA

# 1) Resource group
az group create --name "$RG" --location "$LOCATION"

# 2) Plan Linux
az appservice plan create \
  --name "$PLAN" \
  --resource-group "$RG" \
  --sku "$SKU" \
  --is-linux

# 3) Web App com runtime Python 3.11
az webapp create \
  --resource-group "$RG" \
  --plan "$PLAN" \
  --name "$APP" \
  --runtime "PYTHON:3.11"

# 4) Startup command — chama o startup.sh do repositório
az webapp config set \
  --resource-group "$RG" \
  --name "$APP" \
  --startup-file "startup.sh"

# 5) HTTPS only e versão HTTP 2
az webapp update --resource-group "$RG" --name "$APP" --https-only true
az webapp config set --resource-group "$RG" --name "$APP" --http20-enabled true
```

> **Por que `startup.sh`?** O default do Oryx para Python tenta detectar Flask/Django e chuta um gunicorn genérico. Para uma app ASGI (Starlette/FastAPI) é mais seguro fixar o comando, garantindo o `UvicornWorker` e timeouts adequados para SSE.

---

## 5. Configurar as variáveis de ambiente (App Settings)

As variáveis do `.env` viram **App Settings** no App Service. Elas sobrescrevem o `config.py`.

```bash
az webapp config appsettings set \
  --resource-group "$RG" \
  --name "$APP" \
  --settings \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    MCP_DEBUG=false \
    MCP_RELOAD=false \
    MCP_LOG_LEVEL=INFO \
    MCP_AZURE_RETAIL_PRICES_URL=https://prices.azure.com/api/retail/prices \
    MCP_AZURE_API_VERSION=2023-01-01-preview \
    MCP_HOURS_IN_MONTH=730 \
    MCP_MAX_ALTERNATIVES_TO_SHOW=3 \
    MCP_PRICE_TYPE=Consumption \
    MCP_CORS_ORIGINS="*" \
    SCM_DO_BUILD_DURING_DEPLOYMENT=true \
    WEBSITES_PORT=8000
```

**Notas importantes:**

- `MCP_PORT` e `WEBSITES_PORT` devem coincidir com a porta em que o gunicorn escuta. O `startup.sh` usa `${PORT:-8000}` — o App Service injeta `PORT=8000` por padrão no Python.
- `SCM_DO_BUILD_DURING_DEPLOYMENT=true` faz o Oryx instalar o `requirements.txt` no deploy (mesmo efeito do `.deployment` que já está no repo).
- `MCP_DEBUG=false` é obrigatório em produção.

---

## 6. Restringir acesso por IP (sua escolha de segurança)

Como o endpoint MCP fica exposto na internet pública, vamos limitar quem pode chamá-lo via **Access Restrictions**.

```bash
# 1) Bloqueia tudo por padrão e libera só os IPs informados.
#    Substitua pelos CIDRs reais do escritório, VPN, etc.
az webapp config access-restriction add \
  --resource-group "$RG" \
  --name "$APP" \
  --rule-name "office-vpn" \
  --action Allow \
  --ip-address "203.0.113.10/32" \
  --priority 100

az webapp config access-restriction add \
  --resource-group "$RG" \
  --name "$APP" \
  --rule-name "home-marcio" \
  --action Allow \
  --ip-address "198.51.100.5/32" \
  --priority 200

# 2) (Opcional) Aplicar as MESMAS regras ao painel SCM (Kudu).
#    Sem isso, o painel de administração continua público.
az webapp config access-restriction set \
  --resource-group "$RG" \
  --name "$APP" \
  --use-same-restrictions-for-scm-site true
```

> **Atenção ao GitHub Actions:** se você habilitar Access Restrictions também no SCM, o `azure/webapps-deploy` pode falhar porque o agente do GitHub usa IPs públicos dinâmicos. Soluções:
> - **(Recomendado)** deixar o SCM aberto e proteger apenas o site principal (omita o `--use-same-restrictions-for-scm-site true`); o Kudu já exige credenciais.
> - Ou trocar o deploy para **OIDC + `azure/login`** e adicionar uma regra de Service Tag liberando `AzureCloud` no SCM (mais aberto do que o ideal).
> - Ou migrar para **self-hosted runner** dentro da sua VNet.

---

## 7. Configurar o GitHub Actions

O workflow `.github/workflows/azure-deploy.yml` já foi criado. Para ele funcionar:

### 7.1 Pegar o publish profile

```bash
az webapp deployment list-publishing-profiles \
  --resource-group "$RG" \
  --name "$APP" \
  --xml
```

Copie **todo o XML** retornado.

### 7.2 Criar o secret no GitHub

No repositório, em **Settings → Secrets and variables → Actions → New repository secret**:

- **Name:** `AZURE_WEBAPP_PUBLISH_PROFILE`
- **Value:** o XML inteiro do passo anterior.

### 7.3 Conferir o nome do app no workflow

Em `.github/workflows/azure-deploy.yml`, ajuste se o nome do Web App for diferente:

```yaml
env:
  AZURE_WEBAPP_NAME: mcp-azure-pricing   # ← deve casar com o "$APP" do az CLI
```

### 7.4 Rodar

Faça `git push` na `main` (ou rode manualmente em **Actions → Deploy Azure Pricing MCP to Azure App Service → Run workflow**). O job tem duas etapas:

1. `build` — instala deps em ambiente limpo, roda `pytest` se houver, gera `release.zip`.
2. `deploy` — envia o zip para o App Service; o Oryx detecta o `.deployment` e roda `pip install -r requirements.txt` no servidor.

---

## 8. Validar o deploy

```bash
# Logs em tempo real
az webapp log tail --resource-group "$RG" --name "$APP"

# Endpoints
curl -i https://$APP.azurewebsites.net/tools
curl -N https://$APP.azurewebsites.net/sse   # SSE — não fecha, é normal
```

Você deve ver as linhas do logger Python e a saída JSON do `/tools`.

---

## 9. Cuidados específicos com SSE no App Service

O endpoint MCP usa **Server-Sent Events**, e o App Service tem alguns timeouts agressivos:

- **Idle timeout do front-end (~230 s):** o stream SSE deve enviar bytes periodicamente (heartbeat/keep-alive). O `FastMCP.sse_app()` já costuma fazer isso, mas se você ver desconexões a cada ~4 minutos, é esse o motivo.
- **ARR Affinity:** desabilite se for escalar horizontalmente:
  ```bash
  az webapp update --resource-group "$RG" --name "$APP" --client-affinity-enabled false
  ```
- **Always On:** ative para evitar cold start (não está disponível no **F1** Free; precisa de pelo menos B1):
  ```bash
  az webapp config set --resource-group "$RG" --name "$APP" --always-on true
  ```
- **HTTP/2 e keep-alive longo no gunicorn:** já configurados no `startup.sh` (`--timeout 600 --keep-alive 120`).

---

## 10. Apontar o MCP client para o servidor publicado

No `mcp_config.json` do cliente:

```json
{
  "azure-pricing": {
    "serverUrl": "https://mcp-azure-pricing.azurewebsites.net/sse"
  }
}
```

Lembre-se: o IP de quem está conectando precisa estar na **Access Restrictions** (passo 6).

---

## 11. Troubleshooting

| Sintoma | Provável causa | Correção |
|---|---|---|
| `Application Error` ao acessar | `startup.sh` sem permissão ou nome de app errado em `gunicorn ...:app` | Rodar `az webapp log tail`. Garantir `chmod +x startup.sh` antes do commit, ou que o App Service execute via `bash startup.sh`. |
| `ModuleNotFoundError: pydantic_settings` | `requirements.txt` não foi instalado | Confirmar `SCM_DO_BUILD_DURING_DEPLOYMENT=true` e que `.deployment` está no zip. |
| `503` intermitente sob SSE | Idle timeout / keep-alive curto | Confirmar timeouts do `startup.sh`; subir o plano para P1V3 se carga aumentar. |
| Deploy do GitHub Actions falhando com `403 Ip Forbidden` | Access Restrictions também aplicadas no SCM | Reabrir o SCM (passo 6, nota) ou migrar para OIDC + self-hosted runner. |
| `MCP_HOST` ignorado | Lembre-se: o `if __name__ == "__main__"` não roda no App Service — quem escuta é o gunicorn pelo `startup.sh`. | Conferir `WEBSITES_PORT` e `PORT`. |

---

## 12. Resumo dos comandos (cheat-sheet)

```bash
# 1. Provisionar
az group create -n $RG -l $LOCATION
az appservice plan create -n $PLAN -g $RG --sku B1 --is-linux
az webapp create -g $RG -p $PLAN -n $APP --runtime "PYTHON:3.11"
az webapp config set -g $RG -n $APP --startup-file "startup.sh"

# 2. App settings
az webapp config appsettings set -g $RG -n $APP --settings MCP_DEBUG=false WEBSITES_PORT=8000 ...

# 3. Access Restrictions
az webapp config access-restriction add -g $RG -n $APP --rule-name office --action Allow --ip-address 1.2.3.4/32 --priority 100

# 4. Publish profile → GitHub secret AZURE_WEBAPP_PUBLISH_PROFILE
az webapp deployment list-publishing-profiles -g $RG -n $APP --xml

# 5. git push origin main  →  o GitHub Actions cuida do resto
```

---

## 13. Próximos passos sugeridos

- Trocar `publish-profile` por **OIDC federado** (`azure/login@v2` + Service Principal com `id-token: write`) para evitar segredos de longa duração.
- Configurar **Application Insights** (`az monitor app-insights component create` + `APPLICATIONINSIGHTS_CONNECTION_STRING`) para métricas e tracing.
- Adicionar **slot de staging** e usar `slot-swap` para deploys sem downtime.
- Substituir Access Restrictions por **Private Endpoint** se o MCP client viver dentro de uma VNet Azure.
