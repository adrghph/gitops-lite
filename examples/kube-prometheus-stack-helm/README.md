# Kube-Prometheus-Stack - Monitoring

Deploy Prometheus, Grafana, and Alertmanager using Kustomize + Helm.

## Structure

```
kube-prometheus-stack-helm/
└── base/
    ├── namespace.yaml
    ├── kustomization.yaml
    └── values.yaml
```

## Quick Start

### 1. Create namespace

```bash
kubectl create namespace monitoring --context your-cluster
```

### 2. Link repository

```bash
gitops-lite link https://github.com/user/k8s-manifests \
  --stack monitoring \
  --namespace monitoring \
  --branch main \
  --context your-cluster \
  --renderer-type kustomize \
  --kustomize-dir base \
  --kustomize-build-args '--enable-helm'
```

### 3. Check changes

```bash
gitops-lite plan --stack monitoring
gitops-lite plan --stack monitoring --show-diff
```

### 4. Apply

```bash
gitops-lite apply --stack monitoring --execute
```

### 5. Watch and auto-apply

```bash
gitops-lite watch --stack monitoring --auto-apply --interval 5
```

## Get values.yaml

To get default values from the chart:

```bash
# Add repo
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts

# Search versions
helm search repo kube-prometheus-stack

# Download chart
helm pull prometheus-community/kube-prometheus-stack --version 78.3.1 --untar

# Copy values
cp kube-prometheus-stack/values.yaml ./base/values.yaml
```