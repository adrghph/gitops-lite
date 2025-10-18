# Plain YAML - Simple Deployment

Deploy apps using plain YAML manifests (no Kustomize, no Helm).

## Structure

```
plain-yaml/
├── namespace.yaml
├── nginx-deployment.yaml
└── nginx-service.yaml
```

## Quick Start

### 1. Create namespace

```bash
kubectl create namespace dev --context your-cluster
```

### 2. Link repository

```bash
gitops-lite link https://github.com/user/k8s-manifests \
  --stack dev \
  --namespace dev \
  --branch main \
  --context your-cluster
```

### 3. Check changes

```bash
gitops-lite plan --stack dev
gitops-lite plan --stack dev --show-diff
```

### 4. Apply

```bash
gitops-lite apply --stack dev --execute
```

### 5. Watch and auto-apply

```bash
gitops-lite watch --stack dev --auto-apply --interval 5
```
