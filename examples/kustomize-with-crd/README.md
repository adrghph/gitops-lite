# Kustomize - With CRD

Deploy custom resources with Kustomize overlays for dev and prod environments.

## Structure

```
kustomize-with-crd/
├── base/
│   ├── namespace.yaml
│   ├── crd.yaml
│   ├── custom-resource.yaml
│   ├── configmap.yaml
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
kubectl create namespace demo-webapp-dev --context your-cluster
```

### 2. Link repository

```bash
gitops-lite link https://github.com/user/k8s-manifests \
  --stack demo-webapp-dev \
  --namespace demo-webapp-dev \
  --branch main \
  --context your-cluster \
  --renderer-type kustomize \
  --kustomize-dir overlays/dev
```

### 3. Check changes

```bash
gitops-lite plan --stack demo-webapp-dev
gitops-lite plan --stack demo-webapp-dev --show-diff
```

### 4. Apply

```bash
gitops-lite apply --stack demo-webapp-dev --execute
```

### 5. Watch and auto-apply

```bash
gitops-lite watch --stack demo-webapp-dev --auto-apply --interval 5
```

## Quick Start - Prod

Same steps, replace `demo-webapp-dev` with `demo-webapp-prod` and use `overlays/prod`:

```bash
kubectl create namespace demo-webapp-prod --context prod-cluster

gitops-lite link https://github.com/user/k8s-manifests \
  --stack demo-webapp-prod \
  --namespace demo-webapp-prod \
  --branch main \
  --context prod-cluster \
  --renderer-type kustomize \
  --kustomize-dir overlays/prod

gitops-lite plan --stack demo-webapp-prod --show-diff
gitops-lite apply --stack demo-webapp-prod --execute
gitops-lite watch --stack demo-webapp-prod --auto-apply --interval 5
```

## Verify Deployment

```bash
# Check CRD
kubectl get crd webapps.demo.gitops-lite.io

# Check custom resource
kubectl get webapps -n demo-webapp-dev

# Access web app
kubectl port-forward -n demo-webapp-dev svc/demo-webapp-dev 8080:80
# Open http://localhost:8080
```