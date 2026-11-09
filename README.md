# k8s-platform-demo

Kubernetes prostredie pre jednoduchú webovú appku (frontend + backend). Klaster beží lokálne cez kind, appku nasadzujem vlastným Helm chartom do dvoch prostredí (dev a prod) a do klastra sa prichádza cez Traefik.

> **Toto je vetva `main-bonus`.** Oproti odovzdanej vetve [`main`](https://github.com/samuel10998/k8s-platform-demo/tree/main) má navyše voliteľné časti zo zadania: **GitOps cez Argo CD** a **CI cez GitHub Actions**. Appku tu nenasadzujem cez `helm install` z PC, ale nasadzuje ju Argo CD podľa Gitu a image stavia pipeline.

**Použité technológie:** kind (Kubernetes 1.35.8), Docker, Helm, Traefik, RBAC, NetworkPolicy, Argo CD, GitHub Actions, GitHub Container Registry, Python (Flask), nginx

![Appka cez Ingress](docs/images/faza_4_final.png)

Celý postup, príkazy a problémy, ktoré som riešil, sú v [docs/postup.md](docs/postup.md).

---

## Obsah

- [Dizajn](#dizajn)
- [GitOps a CI](#gitops-a-ci)
- [Bezpečnosť](#bezpečnosť)
- [Štruktúra repa](#štruktúra-repa)
- [Inštalácia](#inštalácia)
- [Použitie](#použitie)
- [Prečo som to spravil takto](#prečo-som-to-spravil-takto)
- [Čo by som doplnil](#čo-by-som-doplnil)

---

## Dizajn

![Diagram architektúry](docs/images/flowchart-diagram.png)

**Ako ide požiadavka:** prehliadač otvorí `dev.localhost` na porte 80. kind presmeruje tento port na port 30080 uzla, kde počúva Traefik. Traefik podľa Ingressu pošle `/api` na backend a všetko ostatné na frontend.

Frontend a backend spolu priamo nekomunikujú. Prehliadač si najprv stiahne stránku z frontendu a potom JavaScript v stránke zavolá `/api/hello` na tej istej adrese.

### Čo je v projekte

| Časť | Kde | Popis |
|---|---|---|
| kind klaster `aspecta` | `cluster/kind-config.yaml` | 1 control-plane a 2 workery, porty 80 a 443 len pre tento PC |
| Traefik | `cluster/traefik-values.yaml` | Ingress controller nainštalovaný cez Helm, vo vlastnom namespace `traefik` |
| frontend | `app/frontend` | statická stránka v nginx, port 8080 |
| backend | `app/backend` | Flask appka, port 8000, má endpointy `/api/hello`, `/healthz` a `/readyz` |
| Helm chart `demo-app` | `charts/demo-app` | všetky Kubernetes objekty appky |
| Argo CD | namespace `argocd` | nasadzuje chart do dev a prod podľa vetvy `main-bonus` |
| Application | `argocd/` | dve Application pre Argo CD, `demo-dev` a `demo-prod` |
| pipeline | `.github/workflows/ci.yaml` | GitHub Actions: build image, push do GHCR a nový tag do chartu |

### Dev a prod

Obe prostredia používajú ten istý chart. Líšia sa len hodnotami, `values-prod.yaml` obsahuje len to, čo je v produkcii inak.

| | dev | prod |
|---|---|---|
| namespace | `demo-dev` | `demo-prod` |
| adresa | `http://dev.localhost` | `http://prod.localhost` |
| počet Podov backend / frontend | 2 / 2 | 3 / 3 |
| `APP_ENV` | `dev` | `prod` |
| Application v Argo CD | `demo-dev` | `demo-prod` (+ `values-prod.yaml`) |

### Škálovanie a dostupnosť

- každá appka má viac replík a Pody sa rozložia na oba workery
- Pody majú nastavené `requests` a `limits` pre CPU a pamäť
- **readiness probe** (`/readyz`): Pod dostane požiadavky, až keď je pripravený. Backend bez `API_KEY` pripravený nie je.
- **liveness probe** (`/healthz`): keď appka zamrzne, Kubernetes ju reštartuje
- keď sa zmení konfigurácia, Pody sa po nasadení vymenia samy (v šablóne je odtlačok ConfigMapy)
- pri novom image ide rolling update: staré Pody bežia, kým nie sú nové Ready, takže appka nevypadne

---

## GitOps a CI

![GitOps a CI](docs/images/main-bonus-diagram.png)

**CI (GitHub Actions):** pri merge zmeny v `app/` do `main-bonus` pipeline:

1. skontroluje chart (`helm lint`)
2. postaví image backendu a frontendu a pushne ich do GitHub Container Registry s tagom z hashu commitu (napr. `a5ef2ea`)
3. zapíše nový tag do `values.yaml` a zvýši verziu chartu
4. zabalí chart (`helm package`) a pushne ho do GHCR
5. commitne zmenu chartu späť do `main-bonus`

**CD (Argo CD):** sleduje `charts/demo-app` vo vetve `main-bonus`. Keď sa tam niečo zmení, či už nový tag od pipeline alebo moja zmena vo values, nasadí to do klastra. Nič nespúšťam ručne.

- `selfHeal`: ručnú zmenu v klastri (napr. `kubectl scale`) Argo CD vráti podľa Gitu
- `prune`: objekt, ktorý zmizne z Gitu, zmaže aj z klastra
- rollback sa robí v Gite cez `git revert`

![Aplikácie v Argo CD](docs/images/faza_6_argocd_apps.png)

---

## Bezpečnosť

### RBAC

- **appky nemajú prístup ku Kubernetes API.** Backend aj frontend majú vlastný ServiceAccount bez práv a do kontajnera sa im nedáva token (`automountServiceAccountToken: false`).
- **používateľ smie len čítať.** Role `demo-viewer` dovoľuje pozerať Pody, logy, Services, ConfigMapy a Deploymenty, ale nie Secrety a nemôže nič meniť ani mazať. Komu sa dá, je v `values.yaml` v `rbac.viewers`.
- práva platia len v namespace appky

### NetworkPolicy

V namespace appky je najprv všetko zakázané a povolené je len to, čo appka naozaj potrebuje:

| Politika | Čo povoľuje |
|---|---|
| `demo-default-deny` | nič, zakáže všetku prevádzku do Podov aj z Podov |
| `demo-allow-dns` | DNS, aby Pody vedeli preložiť mená |
| `demo-backend-from-ingress` | na backend len z Traefiku, port 8000 |
| `demo-frontend-from-ingress` | na frontend len z Traefiku, port 8080 |

Endpointy `/healthz` a `/readyz` nie sú zvonka dostupné, Ingress púšťa na backend len `/api`.

### Kontajnery

- kontajnery nebežia ako root (backend ako používateľ 10001, frontend ako 101)
- v `securityContext` je zakázané spustenie ako root a získanie vyšších práv a sú odobraté všetky Linux capabilities
- všetky image majú presnú verziu, nie `latest`
- Secret nie je v Gite, vytvára sa príkazom pri inštalácii

### Pipeline a Argo CD

- pipeline používa len dočasný `GITHUB_TOKEN` s právami `contents: write` a `packages: write`, žiadne vlastné heslá
- úvodné heslo Argo CD som po prvom prihlásení zmenil a Secret s ním zmazal
- Argo CD je dostupné len cez `kubectl port-forward`, nie cez Ingress

---

## Štruktúra repa

```
k8s-platform-demo/
├── .github/
│   └── workflows/
│       └── ci.yaml         # GitHub Actions pipeline
├── app/
│   ├── backend/            # Flask appka + Dockerfile
│   └── frontend/           # stránka + Dockerfile
├── argocd/
│   ├── app-dev.yaml        # Application pre dev
│   └── app-prod.yaml       # Application pre prod
├── cluster/
│   ├── kind-config.yaml    # nastavenie klastra
│   └── traefik-values.yaml # moje hodnoty pre Traefik
├── charts/
│   └── demo-app/           # Helm chart appky
│       ├── Chart.yaml
│       ├── values.yaml         # dev (tag image mení pipeline)
│       ├── values-prod.yaml    # rozdiely pre prod
│       └── templates/          # šablóny
└── docs/
    ├── postup.md           # postup práce
    └── images/
```

---

## Inštalácia

### Čo treba mať

- Docker Desktop
- [kind](https://kind.sigs.k8s.io/) 0.24 alebo novší (staršie verzie NetworkPolicy neblokujú)
- kubectl (najlepšie 1.34 až 1.36)
- Helm
- voľné porty 80 a 443

Na Windowse sa kind a Helm dajú nainštalovať cez `winget install Kubernetes.kind` a `winget install Helm.Helm`. Príkazy nižšie sú pre PowerShell.

Image si stavať netreba. Postavila ich pipeline a sú verejne v `ghcr.io/samuel10998`.

### 1. Repo

```powershell
git clone -b main-bonus https://github.com/samuel10998/k8s-platform-demo.git
cd k8s-platform-demo
```

### 2. Klaster

```powershell
kind create cluster --config cluster/kind-config.yaml
kubectl wait --for=condition=Ready nodes --all --timeout=180s
```

### 3. Traefik

```powershell
helm repo add traefik https://traefik.github.io/charts
helm repo update
helm install traefik traefik/traefik --version 42.3.0 -f cluster/traefik-values.yaml -n traefik --create-namespace
kubectl wait --for=condition=Ready pods --all -n traefik --timeout=120s
```

### 4. Argo CD

```powershell
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
helm install argocd argo/argo-cd --version 10.15.0 -n argocd --create-namespace --wait
```

### 5. Namespace a Secrety

Secret nie je v Gite, preto ho Argo CD ani Helm nevytvorí a treba ho vytvoriť ručne v oboch prostrediach:

```powershell
kubectl create namespace demo-dev
kubectl create secret generic backend-secret --from-literal=API_KEY=<hodnota> -n demo-dev

kubectl create namespace demo-prod
kubectl create secret generic backend-secret --from-literal=API_KEY=<hodnota> -n demo-prod
```

Namespace a Secret vytváram pred nasadením chartu, lebo Secret nemá byť v Gite a ten istý chart ide do dvoch namespace.

### 6. Appka cez Argo CD

```powershell
kubectl apply -f argocd/
kubectl get applications -n argocd
```

Po chvíli majú byť obe Application `Synced` a `Healthy`. Argo CD si chart stiahne z GitHubu a nasadí ho samo.

### Bez Argo CD, len Helm

Takto som appku nasadzoval vo fázach 3 až 5 (vetva `main`). Namiesto krokov 4 a 6:

```powershell
helm install demo charts/demo-app -n demo-dev
helm install demo charts/demo-app -n demo-prod -f charts/demo-app/values-prod.yaml
kubectl wait --for=condition=Ready pods --all -n demo-dev --timeout=120s
kubectl wait --for=condition=Ready pods --all -n demo-prod --timeout=120s
```

Obe možnosti naraz nepoužívaj. Jednu appku má spravovať buď Helm, alebo Argo CD, inak by si navzájom prepisovali zmeny.

### Zmazanie

```powershell
kind delete cluster --name aspecta
```

---

## Použitie

### Appka

- dev: <http://dev.localhost>
- prod: <http://prod.localhost>

Tlačidlo „Zavolaj backend“ ukáže správu z ConfigMapy, prostredie, ktorý Pod odpovedal a či je nastavený Secret. Adresy končiace na `.localhost` fungujú bez úpravy súboru `hosts`.

```powershell
curl.exe http://dev.localhost/api/hello
curl.exe http://prod.localhost/api/hello
```

### Argo CD

```powershell
kubectl port-forward svc/argocd-server 8081:443 -n argocd
```

V prehliadači `https://localhost:8081` (varovanie o certifikáte je v poriadku), používateľ `admin`. Úvodné heslo:

```powershell
kubectl get secret argocd-initial-admin-secret -n argocd -o jsonpath="{.data.password}"
[System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String("<hodnota>"))
```

Po prihlásení si heslo zmeň (User Info → Update Password) a úvodný Secret zmaž.

### Ako nasadiť zmenu

| Čo meníš | Čo urobíš | Čo sa stane |
|---|---|---|
| kód appky (`app/`) | PR a merge do `main-bonus` | pipeline postaví image a zapíše tag, Argo CD nasadí |
| chart alebo values (`charts/`) | PR a merge do `main-bonus` | Argo CD nasadí priamo, pipeline sa nespustí |
| vrátenie zmeny | `git revert`, PR a merge | Argo CD nasadí predošlý stav |

Po behu pipeline si stiahni jej commit (`git pull` v `main-bonus`), inak budeš mať starý `values.yaml`.

Behy pipeline: [Actions → CI](https://github.com/samuel10998/k8s-platform-demo/actions/workflows/ci.yaml)

Pri variante bez Argo CD sa zmena nasadzuje a vracia cez Helm:

```powershell
# po zmene v charte alebo vo values
helm upgrade demo charts/demo-app -n demo-dev
helm upgrade demo charts/demo-app -n demo-prod -f charts/demo-app/values-prod.yaml

# história a návrat na staršiu verziu
helm history demo -n demo-dev
helm rollback demo <revízia> -n demo-dev
```

### Čo beží

```powershell
helm list -A                                   # Traefik a Argo CD (appku pri Argo CD helm list neukáže)
kubectl get applications -n argocd
kubectl get pods,svc,ingress,networkpolicy -n demo-dev
kubectl get deployment demo-backend -n demo-dev -o jsonpath="{.spec.template.spec.containers[0].image}"
```

### Overenie bezpečnosti

```powershell
# RBAC
kubectl auth can-i list pods -n demo-prod --as samuel      # yes
kubectl auth can-i get secrets -n demo-prod --as samuel    # no
kubectl auth can-i delete pods -n demo-prod --as samuel    # no

# v kontajneri nie je token a nebeží ako root
kubectl exec -n demo-dev deploy/demo-backend -- ls /var/run/secrets/kubernetes.io/serviceaccount   # No such file
kubectl exec -n demo-dev deploy/demo-backend -- id                                                  # uid=10001

# NetworkPolicy: z iného namespace aj z toho istého → timeout
kubectl run test --rm -it --restart=Never --image=busybox:1.37 -n default -- wget -qO- -T 3 http://demo-backend.demo-dev
kubectl run test --rm -it --restart=Never --image=busybox:1.37 -n demo-dev -- wget -qO- -T 3 http://demo-backend
```

---

## Prečo som to spravil takto

| Rozhodnutie | Prečo |
|---|---|
| kind namiesto Kubernetes v Docker Desktope | v Docker Desktope NetworkPolicy nič neblokuje, v kind áno |
| presná verzia Kubernetes v kind configu | každý dostane rovnaký klaster |
| Traefik namiesto ingress-nginx | ingress-nginx sa od marca 2026 už nevyvíja |
| Traefik vo vlastnom namespace | patrí celému klastru, nie jednej appke |
| NodePort namiesto LoadBalancer | kind nemá load balancer, v cloude by som použil LoadBalancer |
| Helm | jedny šablóny pre dev aj prod, upgrade a rollback celej appky naraz |
| namespace a Secret mimo chartu | chart ide do rôznych namespace a Secret nemá byť v Gite |
| `values-prod.yaml` len s rozdielmi | zmena vo `values.yaml` sa prejaví v oboch prostrediach |
| `USER 10001` v Dockerfile ako číslo | Kubernetes vie overiť, že kontajner nebeží ako root, len pri čísle |
| Argo CD (pull) namiesto `helm upgrade` z pipeline (push) | pipeline na GitHube sa k môjmu kind nedostane, Argo CD si zmenu stiahne samo. Git je jediný zdroj pravdy. |
| GitHub Container Registry | je súčasťou GitHubu, pipeline doň pushuje cez `GITHUB_TOKEN` bez ďalších hesiel |
| tag image = krátky hash commitu | každý build má iný tag, takže sa vždy zmení Pod a vidím, z ktorého commitu image je |
| pipeline sa spúšťa len pri zmene v `app/` | commit bota mení `charts/`, takže nevznikne nekonečný cyklus |
| `ingressendpoint.ip=127.0.0.1` v Traefiku | Argo CD považuje Ingress za zdravý až s adresou a pri NodePorte ju Traefik nemal odkiaľ vziať |
| bonus vo vetve `main-bonus` | `main` zostal v stave, v akom som ho odovzdal |

---

## Čo by som doplnil

- **testy v pipeline:** unit testy appky pred buildom, teraz kontroluje len `helm lint`
- **oddelené nasadenie do produ:** pipeline teraz mení tag pre dev aj prod naraz. Lepšie by bolo meniť len dev a do produ posielať verziu samostatným PR po overení.
- **skenovanie image** na zraniteľnosti (napr. Trivy) v pipeline
- **app of apps:** Argo CD by spravovalo aj vlastné Application z priečinka `argocd/`
- **monitoring:** Prometheus a Alertmanager a základné alerty, napríklad keď sa Pod stále reštartuje
- **HTTPS:** certifikáty cez cert-manager
- **lepšie riešenie Secretov:** napríklad Sealed Secrets, aby aj Secret mohol byť v Gite
- **automatické škálovanie** podľa záťaže (HPA) a viac replík Traefiku
- **cloud:** spravovaný klaster (AKS alebo EKS) a skutočná doména

---

Pri práci som používal AI ako mentora: vysvetľovala mi pojmy, kontrolovala moje súbory a keď som sa zasekol, pomohla mi s kódom aj s príkazmi. Všetko som spúšťal a overoval u seba a každej časti rozumiem. Čo som robil prvýkrát a s čím som potreboval pomôcť, je v [docs/postup.md](docs/postup.md).
