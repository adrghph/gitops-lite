# Harbor - Container Registry

Deploy Harbor (open-source container registry) using Kustomize + Helm.

## Structure

```
harbor-helm/
└── base/
    ├── namespace.yaml
    ├── kustomization.yaml
    └── values.yaml
```

## Quick Start

### 1. Create namespace

```bash
kubectl create namespace harbor --context your-cluster
```

### 2. Link repository

```bash
gitops-lite link https://github.com/user/k8s-manifests \
  --stack harbor \
  --namespace harbor \
  --branch main \
  --context your-cluster \
  --renderer-type kustomize \
  --kustomize-dir base \
  --kustomize-build-args '--enable-helm'
```

### 3. Check changes

```bash
gitops-lite plan --stack harbor
gitops-lite plan --stack harbor --show-diff
```

### 4. Apply

```bash
gitops-lite apply --stack harbor --execute
```

### 5. Watch and auto-apply

```bash
gitops-lite watch --stack harbor --auto-apply --interval 5
```

## Access Harbor

```bash
# Wait for pods to be ready
kubectl wait --for=condition=Ready pods --all -n harbor --timeout=600s

# Port-forward
kubectl port-forward -n harbor svc/harbor-core 8080:80

# Open browser
open http://localhost:8080
```

**Default credentials:**
- Username: `admin`
- Password: `Harbor12345`

## Get values.yaml

To get default values from Harbor chart:

```bash
# Add repo
helm repo add harbor https://helm.goharbor.io

# Search versions
helm search repo harbor

# Download chart
helm pull harbor/harbor --version 1.18.0 --untar

# Copy values
cp harbor/values.yaml ./base/values.yaml
```