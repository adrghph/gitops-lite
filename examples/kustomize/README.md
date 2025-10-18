# Kustomize - Base + Overlays

Deploy apps with Kustomize overlays for dev and prod environments.

## Structure

```
kustomize/
├── base/
│   ├── namespace.yaml
│   ├── deployment.yaml
│   ├── service.yaml
│   └── kustomization.yaml
└── overlays/
    ├── dev/
    │   └── kustomization.yaml
    └── prod/
        └── kustomization.yaml
```

## Quick Start - Dev

### 1. Create namespace

```bash
kubectl create namespace myapp-dev --context your-cluster
```

### 2. Link repository

```bash
gitops-lite link https://github.com/user/k8s-manifests \
  --stack myapp-dev \
  --namespace myapp-dev \
  --branch main \
  --context your-cluster \
  --renderer-type kustomize \
  --kustomize-dir overlays/dev
```

### 3. Check changes

```bash
gitops-lite plan --stack myapp-dev
gitops-lite plan --stack myapp-dev --show-diff
```

### 4. Apply

```bash
gitops-lite apply --stack myapp-dev --execute
```

### 5. Watch and auto-apply

```bash
gitops-lite watch --stack myapp-dev --auto-apply --interval 5
```

## Quick Start - Prod

Same steps, replace `myapp-dev` with `myapp-prod` and use `overlays/prod`:

```bash
kubectl create namespace myapp-prod --context prod-cluster

gitops-lite link https://github.com/user/k8s-manifests \
  --stack myapp-prod \
  --namespace myapp-prod \
  --branch main \
  --context prod-cluster \
  --renderer-type kustomize \
  --kustomize-dir overlays/prod

gitops-lite plan --stack myapp-prod --show-diff
gitops-lite apply --stack myapp-prod --execute
gitops-lite watch --stack myapp-prod --auto-apply --interval 5
```