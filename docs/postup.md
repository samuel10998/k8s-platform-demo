# Postup

Moje poznámky k projektu: čo som robil, aké príkazy som použil a čo mi nefungovalo. Návod na inštaláciu je v README.

Robím na Windows 11 v PowerShelli, s Docker Desktopom, kind, kubectl 1.34.1 (je z Docker Desktopu) a Helmom.

Pri práci som používal AI ako pomoc (vysvetlenia, kontrola chýb, keď som sa zasekol). Dockerfiles a YAML som písal sám a všetko som spúšťal u seba.

---

## Fáza 0 – prostredie

### Nástroje

kind a Helm som nainštaloval cez winget. Potom treba PowerShell zavrieť a otvoriť znova, inak príkazy nenájde.

```powershell
winget install Kubernetes.kind
winget install Helm.Helm
kind version
helm version
kubectl version --client
```

kind: doplniť, Helm: doplniť, kubectl: 1.34.1

### Repo

Na GitHube som vytvoril verejný repozitár `k8s_platform_demo` s README a MIT licenciou a naklonoval som ho do Documents. Appku (backend a frontend) som rozbalil do priečinka `app`.

Do `.gitignore` som dal `logs/`, lebo tam ukladám nahrávky terminálu a je v nich meno PC a môžu tam byť aj heslá.

```powershell
git status          # logs/ tam nie je, takže .gitignore funguje
git add .
git commit -m "feat: add demo app"
git push
```

### Nahrávanie terminálu

Aby som mal záznam toho, čo som robil, nahrávam PowerShell cez `Start-Transcript`. Nahráva sa len to jedno okno. Keď ho zavriem alebo otvorím nové, treba to spustiť znova s `-Append`.

```powershell
Start-Transcript -Path .\logs\faza0.txt
Start-Transcript -Path .\logs\faza0.txt -Append    # po pauze
Stop-Transcript
```

### Dockerfiles

Backend (`app/backend/Dockerfile`):

```dockerfile
FROM python:3.12.16-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --uid 10001 --create-home appuser
COPY app.py .
USER 10001
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "app:app"]
```

- najprv kopírujem `requirements.txt` a inštalujem knižnice, až potom `app.py`, aby sa pri zmene kódu knižnice nemuseli inštalovať znova (cache)
- používateľ má pevné UID 10001, lebo Kubernetes pri `runAsNonRoot` vie skontrolovať len číslo, nie meno
- gunicorn namiesto servera z Flasku, ten je len na vývoj

Frontend (`app/frontend/Dockerfile`):

```dockerfile
FROM nginx/nginx-unprivileged:1.30.6-alpine
COPY index.html /usr/share/nginx/html/index.html
EXPOSE 8080
```

- nginx-unprivileged beží bez roota (UID 101), preto port 8080 (pod 1024 môže len root)
- `index.html` prepíše predvolenú stránku „Welcome to nginx“

Build:

```powershell
docker build -t backend:0.1.0 app\backend
docker build -t frontend:0.1.0 app\frontend
```

Verzie som dal presné, aby sa image o mesiac postavil rovnako, a tag `0.1.0` namiesto `latest`, lebo pri `latest` by Kubernetes image vždy hľadal na Docker Hube.

### Test cez docker run

```powershell
# backend bez API_KEY
docker run -d --name backend-test -p 8000:8000 backend:0.1.0
curl.exe -i http://localhost:8000/api/hello
curl.exe -i http://localhost:8000/healthz
curl.exe -i http://localhost:8000/readyz
docker exec backend-test id

# backend s API_KEY
docker rm -f backend-test
docker run -d --name backend-test -p 8000:8000 -e API_KEY=test123 -e APP_ENV=lokal backend:0.1.0
curl.exe -i http://localhost:8000/readyz
curl.exe http://localhost:8000/api/hello

# frontend
docker run -d --name frontend-test -p 8080:8080 frontend:0.1.0
docker exec frontend-test id

docker rm -f backend-test frontend-test
```

V PowerShelli treba písať `curl.exe`, lebo samotné `curl` je tam niečo iné.

Čo vyšlo:

- backend bez `API_KEY`: `/api/hello` a `/healthz` vrátili 200, `/readyz` vrátil 503
- backend s `API_KEY`: `/readyz` vrátil 200, v `/api/hello` je `environment: lokal` a `secret_configured: true`
- backend beží ako `uid=10001(appuser)`
- frontend: stránka sa ukáže, tlačidlo píše HTTP 404, lebo nginx nemá `/api` (to vyrieši Ingress)
- frontend beží ako `uid=101(nginx)`

```powershell
git add .
git commit -m "feat: dockerfiles"
git push
```

### kind klaster

Kubernetes v Docker Desktope NetworkPolicy neblokuje, preto som použil kind. Klaster mám v súbore `cluster/kind-config.yaml`: 1 control-plane, 2 workery, Kubernetes 1.35.8 a porty 80 a 443 len na `127.0.0.1`, aby klaster nebol dostupný z domácej siete.

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: aspecta

nodes:
  - role: control-plane
    image: kindest/node:v1.35.8@sha256:07b2536e30b803ed61d1677a79df6115f798ce64c80f9e22f6ed45afd09323c0
    extraPortMappings:
      - containerPort: 30080
        hostPort: 80
        listenAddress: "127.0.0.1"
        protocol: TCP
      - containerPort: 30443
        hostPort: 443
        listenAddress: "127.0.0.1"
        protocol: TCP

  - role: worker
    image: kindest/node:v1.35.8@sha256:07b2536e30b803ed61d1677a79df6115f798ce64c80f9e22f6ed45afd09323c0

  - role: worker
    image: kindest/node:v1.35.8@sha256:07b2536e30b803ed61d1677a79df6115f798ce64c80f9e22f6ed45afd09323c0
```

Porty 30080 a 30443 sú preto, lebo tam neskôr bude NodePort Traefiku (NodePorty sú v rozsahu 30000–32767).

```powershell
kind create cluster --config cluster\kind-config.yaml
kubectl config current-context        # kind-aspecta
kubectl version
kubectl wait --for=condition=Ready nodes --all --timeout=120s
kubectl get nodes
docker ps
```

Prvý klaster som vytvoril bez `image` a dostal som Kubernetes 1.37. kubectl hlásil, že je to oproti mojej verzii 1.34 moc veľký rozdiel. Klaster som zmazal a ku každému uzlu som pridal image s verziou 1.35.8. Musí byť pri všetkých troch, inak by workery mali inú verziu ako control-plane.

### Image do klastra

Uzly kind nevidia image z Docker Desktopu, treba ich tam nahrať:

```powershell
kind load docker-image backend:0.1.0 frontend:0.1.0 --name aspecta
docker exec aspecta-worker crictl images | findstr "backend frontend"
```

### Test NetworkPolicy

Chcel som si overiť, že kind NetworkPolicy naozaj blokuje.

```powershell
kubectl create namespace np-test
kubectl run web --image=nginx:1.30.6-alpine --labels=app=web --port=80 -n np-test
kubectl expose pod web --port=80 -n np-test
kubectl wait --for=condition=Ready pod/web -n np-test --timeout=60s

# bez politiky
kubectl run test --rm -it --restart=Never --image=busybox:1.37 -n np-test -- wget -qO- -T 3 http://web

kubectl apply -f C:\Users\samue\Desktop\np-test.yaml

# s politikou
kubectl run test --rm -it --restart=Never --image=busybox:1.37 -n np-test -- wget -qO- -T 3 http://web

kubectl delete namespace np-test
```

`np-test.yaml`:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: zakaz-vsetko
  namespace: np-test
spec:
  podSelector: {}
  policyTypes:
    - Ingress
```

Bez politiky busybox stiahol stránku nginx, s politikou skončil `download timed out`, takže to funguje. DNS išlo aj tak, lebo politika blokuje len prichádzajúcu prevádzku do Podov.

```powershell
git add .
git commit -m "feat: kind config"
git push
```

### S čím som si potreboval pomôcť
- čo sú kind a Helm a ako ich nainštalovať
- ako sa klaster opíše v `kind-config.yaml` (uzly, `extraPortMappings`) a prečo porty 30080 a 30443
- prečo sa klaster vytvára cez `kind create cluster` a nie cez `kubectl apply`
- `kind load docker-image` a ako sa pozrieť do uzla cez `crictl images`
- ako zafixovať verziu Kubernetes v kind cez `image` s digestom
- pevné UID v Dockerfile (`USER 10001` namiesto `USER appuser`): Kubernetes pri `runAsNonRoot` vie overiť len číslo, pri mene by Pod nenaštartoval 
- aký tag `nginx-unprivileged` vybrať a prečo `alpine` a nie Debian (tag bez prípony je Debian, 58 MB oproti 21 MB)
- `Start-Transcript` na nahrávanie terminálu. Prvýkrát som to používal na zapisovanie logov naživo.
- Klaster cez YAML súbor (`kind-config.yaml`) som robil prvýkrát. Musel som si pomôcť so štruktúrou súboru a s tým, ako sa z neho klaster vytvorí.
- NetworkPolicy som tiež robil prvýkrát. Musel som si pomôcť s tým, ako funguje a ako otestovať, že naozaj blokuje.

### Problémy

- Pri `docker build` som omylom dal dve cesty naraz a hlásil, že chce 1 argument.
- Najnovšie verzie nginx-unprivileged neboli pod `nginxinc`, sú pod `nginx/nginx-unprivileged`.
- Tag `1.30.6` bez prípony je Debian (58 MB), správny je `1.30.6-alpine` (21 MB).
- `/readyz` hneď po štarte vrátil `Empty reply from server`, gunicorn ešte nebežal. O sekundu neskôr to bolo OK.
- Po prvom vytvorení klastra hlásil `kubectl version`, že môj kubectl 1.34 a klaster 1.37 sú od seba moc ďaleko (podporovaný rozdiel je 1 verzia). S pomocou AI som do configu pridal image s verziou 1.35.8. Zistil som, že musí byť pri všetkých troch uzloch, inak by workery dostali predvolenú 1.37 a mali by inú verziu ako control-plane.
- `Stop-Transcript` hlásil, že nič nenahráva. Omylom som zavrel PowerShell a v novom okne som nahrávanie znova nespustil.

---

## Fáza 1 – appka v klastri

### Súbory v k8s/

- `00-namespace.yaml` – namespace `demo-dev`
- `10-backend-config.yaml` – ConfigMap `backend-config` s `APP_GREETING` a `APP_ENV: dev`
- `20-backend.yaml` – Deployment `backend` a Service `backend-service`
- `30-frontend.yaml` – Deployment `frontend` a Service `frontend-service`

Čísla pred menami sú preto, lebo `kubectl apply -f k8s\` berie súbory abecedne a namespace musí byť prvý. Sú po desiatkach, aby sa dal neskôr vložiť súbor medzi ne.

Backend:

- 2 repliky, image `backend:0.1.0`, port 8000
- premenné z ConfigMapy aj zo Secretu cez `envFrom`
- requests `cpu: 50m`, `memory: 64Mi`, limits `cpu: 200m`, `memory: 128Mi`
- readiness probe na `/readyz` (bez `API_KEY` Pod nebude Ready), liveness probe na `/healthz`
- Service ClusterIP, port 80 → 8000

Frontend:

- 2 repliky, image `frontend:0.1.0`, port 8080
- requests `cpu: 25m`, `memory: 32Mi`, limits `cpu: 100m`, `memory: 64Mi`
- readiness aj liveness probe na `/`
- Service ClusterIP, port 80 → 8080

Obe Services majú port 80, aby sa na ne Ingress vo fáze 2 pripájal rovnako.

### Secret

Secret nie je v Gite, vytváram ho príkazom. Najprv musí existovať namespace:

```powershell
kubectl apply -f k8s\00-namespace.yaml
kubectl create secret generic backend-secret --from-literal=API_KEY=<hodnota> -n demo-dev
```

### Nasadenie

```powershell
kubectl apply --dry-run=client -f k8s\        # kontrola súborov, nič sa nevytvorí
kubectl apply -f k8s\
kubectl wait --for=condition=Ready pods --all -n demo-dev --timeout=120s
kubectl get pods -n demo-dev -o wide
kubectl get endpointslices -n demo-dev
```

`kubectl get endpoints` funguje tiež, ale od Kubernetes 1.33 hlási, že je zastaraný, preto `endpointslices`.

### Overenie

```powershell
# backend cez Service, viackrát
kubectl run test --rm -it --restart=Never --image=busybox:1.37 -n demo-dev -- wget -qO- -T 3 http://backend-service/api/hello

# frontend cez Service
kubectl run test --rm -it --restart=Never --image=busybox:1.37 -n demo-dev -- wget -qO- -T 3 http://frontend-service

# prehliadač
kubectl port-forward svc/frontend-service 8080:80 -n demo-dev
```

Čo vyšlo:

- 4 Pody `1/1 Running`, z každej appky jeden na `aspecta-worker` a jeden na `aspecta-worker2`
- každá Service má 2 endpointy, v nich sú IP Podov a porty 8000 a 8080 (nie 80, endpointy ukazujú priamo na Pody)
- `/api/hello` vrátil `environment: dev`, správu z ConfigMapy a `secret_configured: true`, odpovedali oba Pody
- `http://frontend-service` vrátil HTML stránky
- `http://frontend-service/api/hello` vrátil 404, lebo nginx nemá `/api`
- cez port-forward sa stránka ukázala na `localhost:8080`, tlačidlo píše HTTP 404 (vyrieši Ingress)

![Frontend cez port-forward](images/faza_1_port_forward_test.png)

### Git

Od tejto fázy robím každú fázu vo vlastnej vetve a do `main` ju dávam cez pull request.

```powershell
git switch -c faza-1
git add k8s docs
git commit -m "feat: k8s manifesty pre appku"
git push -u origin faza-1
# PR na GitHube, merge
git switch main
git pull
```

### S čím som si potreboval pomôcť

- prečo čísla pred menami súborov (zistil som, že `kubectl apply -f k8s\` berie súbory abecedne, takže s číslami ich aplikuje v poradí, v akom ich potrebujem, napr. namespace ako prvý, lebo ostatné objekty doň patria)
- `--dry-run=client` na celý priečinok (zistil som, že spracuje súbory ako apply, ale nič nevytvorí. Keď je v súbore chyba, dozviem sa to skôr, ako by som chybný súbor aplikoval do klastra. Zachytí ale len chyby v zápise, nie napr. zlé meno Service alebo zlý port)
- `endpointslices` namiesto `endpoints` (zistil som, že starý objekt Endpoints je od Kubernetes 1.33 zastaraný a nahradili ho EndpointSlices, ktoré sa pri veľkom počte Podov dajú rozdeliť na viac častí)
- ako napísať readiness a liveness probe a aký je medzi nimi rozdiel

### Problémy

- V Deploymente backendu som mal 2 chyby: `ports` som nemal ako zoznam a v probes som mal `port` vedľa `httpGet` namiesto pod ním (`path` a `port` patria pod `httpGet`).

---

## Fáza 3 – vlastný Helm chart

Cieľ bol mať celú appku ako jeden balík, ktorý sa nainštaluje jedným príkazom, s inými hodnotami pre dev a prod. Ten istý chart budú neskôr nasadzovať Argo CD a pipeline.

### Príprava

```powershell
git switch main
git pull
git switch -c faza-3
Start-Transcript -Path .\logs\faza3.txt -Append
```

Objekty z fázy 1 vytvoril `kubectl apply`, nie Helm, a Helm cudzie objekty s rovnakým menom neprevezme. Preto som ich zmazal, ale nie namespace a Secret:

```powershell
kubectl delete -f k8s\40-ingress.yaml -f k8s\30-frontend.yaml -f k8s\20-backend.yaml -f k8s\10-backend-config.yaml
kubectl get all,configmap,secret,ingress -n demo-dev
```

Pody a ReplicaSety boli vo výpise ešte chvíľu vidieť, mazanie ide kaskádovo na pozadí. Potom zostal len `backend-secret` a systémová `kube-root-ca.crt`.

### Štruktúra chartu

```
charts/demo-app/
├── Chart.yaml
├── values.yaml         # predvolené hodnoty = dev
├── values-prod.yaml    # len rozdiely pre prod
└── templates/
    ├── configmap.yaml
    ├── backend.yaml     # Deployment + Service
    ├── frontend.yaml    # Deployment + Service
    └── ingress.yaml
```

`Chart.yaml`:

```yaml
apiVersion: v2
name: demo-app
description: Helm chart pre demo appku – frontend (nginx), backend (Flask) a Ingress.
type: application
version: 0.1.0
appVersion: "0.1.0"
```

`version` je verzia chartu, `appVersion` verzia appky.

### values.yaml (dev)

```yaml
config:
  greeting: "Ahoj z config mapy"
  appEnv: "dev"

backend:
  replicas: 2
  image:
    repository: backend
    tag: "0.1.0"
  existingSecret: backend-secret
  resources:
    requests:
      cpu: 50m
      memory: 64Mi
    limits:
      cpu: 200m
      memory: 128Mi

frontend:
  replicas: 2
  image:
    repository: frontend
    tag: "0.1.0"
  resources:
    requests:
      cpu: 25m
      memory: 32Mi
    limits:
      cpu: 100m
      memory: 64Mi

ingress:
  className: traefik
  host: dev.localhost
```

### Šablóny

Šablóny som spravil z manifestov z `k8s/`. Zmenil som len miesta, ktoré sa medzi prostrediami líšia:

- mená objektov cez `{{ .Release.Name }}`: `demo-config`, `demo-backend`, `demo-frontend`, Ingress `demo`
- `namespace` som zo šablón vymazal, určí ho `-n` pri inštalácii
- štítky namiesto `app: backend`: `app.kubernetes.io/name` a `app.kubernetes.io/instance: {{ .Release.Name }}`, rovnaké v selectore Deploymentu, v šablóne Podu aj v selectore Service
- repliky, image a resources z values
- odkazy (`envFrom` na ConfigMap, Ingress na Services) cez ten istý výraz ako meno cieľa
- Ingress má navyše `host` z values

Príklady z `backend.yaml`:

```yaml
          image: "{{ .Values.backend.image.repository }}:{{ .Values.backend.image.tag }}"
          envFrom:
            - configMapRef:
                name: {{ .Release.Name }}-config
            - secretRef:
                name: {{ .Values.backend.existingSecret }}
          resources:
            {{- toYaml .Values.backend.resources | nindent 12 }}
```

`toYaml | nindent 12` vloží celý blok z values, číslo je počet medzier pred `requests:`.

`configmap.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ .Release.Name }}-config
data:
  APP_GREETING: {{ .Values.config.greeting | quote }}
  APP_ENV: {{ .Values.config.appEnv | quote }}
```

Vľavo je meno premennej, ktorú číta appka, vpravo cesta do `values.yaml`. `quote` dá hodnotu do úvodzoviek, aby bola vždy text.

### Kontrola a inštalácia dev

```powershell
helm lint charts\demo-app  # Kontrolujem, či som v charte nespravil nejakú hlúpu chybu alebo preklep.
helm template demo charts\demo-app -s templates/backend.yaml  # Chcem vidieť, ako sa vyrenderuje čisté YAMLko iba pre backend, nech to hneď nenasadzujem.
helm install demo charts\demo-app -n demo-dev  # Sypem to tam – inštalujem appku pod názvom "demo" do namespace "demo-dev".
kubectl wait --for=condition=Ready pods --all -n demo-dev --timeout=120s  # Čakám (max 2 minúty), kým všetky pody konečne nazelenajú a budú ready.
kubectl get pods,svc,ingress -n demo-dev  
helm list -n demo-dev # Kontrolujem, čo všetko mi vlastne v tom namespace cez Helm beží.
```

Čo vyšlo:

- `helm lint` bez chýb, len odporúčanie pridať ikonu
- Helm vo výstupe `helm template` zoradil Service pred Deployment, objekty triedi podľa druhu sám
- release `demo`, revízia 1, 4 Pody `1/1`, Services `demo-backend`, `demo-frontend`, Ingress s `HOSTS dev.localhost`
- `http://dev.localhost` ukáže stránku s `Prostredie: dev`
- `http://localhost` teraz vracia 404 od Traefiku, lebo Ingress má `host: dev.localhost` a na `localhost` žiadne pravidlo nesedí
- adresy končiace na `.localhost` prehliadač aj curl prekladajú na `127.0.0.1`, netreba meniť súbor `hosts`

### Prod

`values-prod.yaml`, len rozdiely:

```yaml
config:
  greeting: "Ahoj z produkcie"
  appEnv: "prod"

backend:
  replicas: 3

frontend:
  replicas: 3

ingress:
  host: prod.localhost
```

Helm vnorené kľúče zlučuje, takže image, resources a Secret sa vezmú z `values.yaml`.

```powershell
helm template demo charts\demo-app -f charts\demo-app\values-prod.yaml | Select-String "replicas|APP_ENV|host:|image:"

kubectl create namespace demo-prod
kubectl create secret generic backend-secret --from-literal=API_KEY=<hodnota> -n demo-prod
helm install demo charts\demo-app -f charts\demo-app\values-prod.yaml -n demo-prod

kubectl wait --for=condition=Ready pods --all -n demo-prod --timeout=120s
helm list -A
curl.exe http://prod.localhost/api/hello
curl.exe http://dev.localhost/api/hello
```

Čo vyšlo:

- v `demo-prod` 6 Podov (3 + 3), `environment: prod` a prod správa
- dev beží ďalej s `environment: dev`
- `helm list -A` ukáže dva releasy `demo` v dvoch namespace a Traefik
- hash ReplicaSetu je v dev aj prode rovnaký, lebo šablóna Podu je rovnaká, líši sa len ConfigMap a počet replík

### Upgrade a rollback

Zmenil som `greeting` vo `values.yaml` a spravil upgrade:

```powershell
helm upgrade demo charts\demo-app -n demo-dev
kubectl get pods -n demo-dev
curl.exe http://dev.localhost/api/hello
kubectl get configmap demo-config -n demo-dev -o yaml | Select-String APP_GREETING
```

ConfigMap sa zmenila, ale Pody sa nereštartovali a API vracalo starú správu. Premenné z `envFrom` sa načítajú len pri štarte kontajnera a šablóna Podu zostala rovnaká, takže Deployment nemal dôvod Pody vymeniť.

Opravil som to anotáciou s odtlačkom ConfigMapy v šablóne Podu backendu:

```yaml
      annotations:
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
```

Po ďalšom upgrade vznikol nový ReplicaSet, Pody sa vymenili (rolling update) a API vrátilo novú správu. Frontend sa nezmenil, lebo jeho šablóna je rovnaká.

```powershell
helm history demo -n demo-dev
helm rollback demo 1 -n demo-dev
kubectl get pods -n demo-dev
curl.exe http://dev.localhost/api/hello
helm history demo -n demo-dev
```

- rollback vrátil všetko z revízie 1 naraz, ConfigMap aj Deployment, vrátil sa aj pôvodný hash ReplicaSetu
- rollback je v histórii nová revízia 4 „Rollback to 1“, história sa neprepisuje

Nakoniec som vrátil `greeting` a spravil upgrade oboch prostredí, aby klaster sedel s chartom v Gite:

```powershell
helm upgrade demo charts\demo-app -n demo-dev
helm upgrade demo charts\demo-app -n demo-prod -f charts\demo-app\values-prod.yaml
```

Pri prode treba vždy `-f`, inak by dostal dev hodnoty.

### Git

Priečinok `k8s/` som zmazal, lebo chart je teraz jediný zdroj pravdy. Staré manifesty zostali v histórii Gitu a v tomto postupe.

```powershell
git rm -r -f k8s
git add charts
git commit -m "feat: helm chart pre appku, dev a prod"
git push -u origin faza-3
# PR na GitHube, merge
git switch main
git pull
```

### S čím som si potreboval pomôcť

- čo je šablóna a na čo je chart (zistil som, že šablóna je môj manifest, v ktorom sú premenlivé miesta nahradené `{{ }}` a Helm ich doplní z values, takže dev a prod používajú tie isté šablóny a líšia sa len hodnotami)
- rozdiel medzi values pri Traefiku a pri mojom charte (zistil som, že pri vlastnom charte píšem šablóny aj `values.yaml` so všetkými hodnotami a `values-prod.yaml` má len rozdiely, ako môj súbor pri Traefiku)
- `values.yaml` som si nechal pomôcť napísať, hodnoty sú z mojich manifestov z fázy 1
- `toYaml | nindent` a `quote` (zistil som, že `toYaml` vloží celý blok z values a číslo pri `nindent` je počet medzier, `quote` dá hodnotu do úvodzoviek)
- prečo `{{ .Release.Name }}` v menách (zistil som, že tak sa dva releasy nebijú a odkazy musia používať ten istý výraz ako cieľ)
- prečo sa zmena ConfigMapy neprejavila a ako to opraviť cez checksum anotáciu
- `helm history` a `helm rollback` (zistil som, že rollback je nová revízia a vráti celú appku naraz)
- prečo zmazať `k8s/` (zistil som, že nejde o bezpečnosť, ale o to, aby bol jeden zdroj pravdy.)

### Problémy

- V šablóne ConfigMapy som mal vymenené strany: vľavo cesty z values a vpravo mená premenných. Vľavo musí byť meno, ktoré číta appka (`APP_GREETING`), vpravo cesta do values (`.Values.config.greeting`). Helm pri neexistujúcej ceste nehlási chybu, len dosadí prázdnu hodnotu.
- Šablónu Ingressu som skopíroval z `k8s/` a zostali v nej staré mená Services (`backend-service`) bez `host`. Odkaz musí používať ten istý výraz ako šablóna Service (`{{ .Release.Name }}-backend`).
- `values-prod.yaml` som najprv spravil ako kópiu celého `values.yaml`. Má obsahovať len rozdiely, inak by sa zmena vo `values.yaml` do produ nedostala.


