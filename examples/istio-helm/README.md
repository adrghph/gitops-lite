# Istio - Service Mesh

Deploy Istio (service mesh) using Kustomize + Helm.

**Requirements:** Kubernetes cluster with 4Gi+ RAM

## Structure

```
istio-helm/
└── base/
    ├── namespace.yaml
    ├── kustomization.yaml
    ├── values-istiod.yaml
    └── values-base.yaml
```

## Quick Start

### 1. Create namespace

```bash
kubectl create namespace istio-system --context your-cluster
```

### 2. Link repository

```bash
gitops-lite link https://github.com/user/k8s-manifests \
  --stack istio \
  --namespace istio-system \
  --branch main \
  --context your-cluster \
  --renderer-type kustomize \
  --kustomize-dir base \
  --kustomize-build-args '--enable-helm'
```

### 3. Check changes

```bash
gitops-lite plan --stack istio
gitops-lite plan --stack istio --show-diff
```

### 4. Apply

```bash
gitops-lite apply --stack istio --execute
```

### 5. Watch and auto-apply

```bash
gitops-lite watch --stack istio --auto-apply --interval 5
```

## Get values.yaml

To get default values from Istio charts:

```bash
# Add repo
helm repo add istio https://istio-release.storage.googleapis.com/charts

# Search versions
helm search repo istio

# Download base chart
helm pull istio/base --version 1.24.2 --untar

# Download istiod chart
helm pull istio/istiod --version 1.24.2 --untar

# Copy values
cp base/values.yaml ./base/values-base.yaml
cp istiod/values.yaml ./base/values-istiod.yaml
```