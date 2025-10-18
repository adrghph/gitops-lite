# GitOps-Lite Examples

This directory contains examples demonstrating how to use **gitops-lite** with Kustomize and Helm charts for deploying applications to Kubernetes.

## Table of Contents

- [Understanding Kustomize + Helm Integration](#understanding-kustomize--helm-integration)
- [How CRDs Are Handled](#how-crds-are-handled)
- [Quick Start](#quick-start)
- [Available Examples](#available-examples)
- [Command Reference](#command-reference)
- [Common Patterns](#common-patterns)
- [Troubleshooting](#troubleshooting)

---

## Understanding Kustomize + Helm Integration

GitOps-lite leverages **Kustomize's Helm integration** to render Helm charts without running Helm directly. This approach provides several advantages:

### How It Works

1. **Kustomize downloads Helm charts** to a local `charts/` directory
2. **Helm renders templates** using your custom `values.yaml`
3. **Kustomize processes the output** (adds labels, sets namespaces, etc.)
4. **GitOps-lite applies to cluster** using `kubectl apply --server-side`

### Benefits

- ✅ **No Helm required in cluster** - Pure kubectl apply workflow
- ✅ **Declarative configuration** - Everything in Git
- ✅ **Automatic CRD handling** - No manual pre-installation needed
- ✅ **Resource labeling** - Track which stack manages which resources
- ✅ **Server-side apply** - Better conflict resolution

### Basic Structure

Every Helm-based example follows this structure:

```
example-name/
├── base/
│   ├── namespace.yaml           # Target namespace
│   ├── kustomization.yaml       # Kustomize + Helm config
│   ├── values.yaml              # Helm chart values
│   └── .gitignore               # Ignore charts/ directory
└── README.md                    # Example-specific docs
```

### kustomization.yaml Template

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# Force namespace for all resources (required for some charts)
namespace: my-namespace

resources:
- namespace.yaml

helmCharts:
- name: chart-name
  repo: https://helm-repo-url.com
  version: 1.2.3
  releaseName: my-release
  namespace: my-namespace
  includeCRDs: false  # gitops-lite handles CRDs automatically
  valuesFile: values.yaml
```

**Important Notes:**

- `namespace: my-namespace` (top-level) forces namespace on ALL resources
- Some Helm charts don't properly set namespaces - use top-level `namespace:` to fix this
- `includeCRDs: false` - Always set this, gitops-lite handles CRDs automatically
- `valuesFile: values.yaml` - Custom configuration for the Helm chart

---

## How CRDs Are Handled

GitOps-lite automatically detects and manages **Custom Resource Definitions (CRDs)** from three sources:

### 1. Helm Chart CRDs (via Kustomize)

When using `--enable-helm`, Kustomize downloads charts to `charts/` directory. GitOps-lite:

1. **Scans `charts/` directory** for CRD files after Kustomize download
2. **Validates CRDs** by checking `kind: CustomResourceDefinition`
3. **Applies CRDs first** using `kubectl apply --server-side --force-conflicts`
4. **Then processes other resources**

**Example output:**
```
Rendering Kustomize from /path/to/example/base...
  Extra args: --enable-helm
[OK] Kustomize rendering complete
Found 42 CRD(s) in Helm chart(s)
  Applying CRDs first (server-side apply)...
    ✓ monitoring.coreos.com_prometheuses.yaml
    ✓ monitoring.coreos.com_alertmanagers.yaml
    ...
  ✓ All CRDs applied successfully
```

### 2. CRDs in Plain YAML Files

If you have CRD files in your manifests:

1. **Automatic sorting** - CRDs get order priority `2` (after Namespaces)
2. **Applied before other resources** - Dependencies work correctly
3. **Split application** - CRDs applied first, then other resources

### 3. CRDs via Kustomize (without Helm)

Standard Kustomize resources with CRDs are handled the same as plain YAML.

### Resource Application Order

GitOps-lite applies resources in this order:

```
1  → Namespace
2  → CustomResourceDefinition (CRDs)
10 → ConfigMap, Secret
20 → PersistentVolume, PersistentVolumeClaim, StorageClass
30 → ServiceAccount
31 → Role, ClusterRole
32 → RoleBinding, ClusterRoleBinding
40 → Service
50 → Deployment, StatefulSet, DaemonSet, Job, CronJob
60 → Ingress, Route
70 → NetworkPolicy, LimitRange, ResourceQuota
100 → Everything else
```

**Custom ordering:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-config
  annotations:
    gitops-lite.io/order: "5"  # Override default order (10)
```

---

## Quick Start

### 1. Link a Stack

```bash
gitops-lite link ./examples/cert-manager-example/base \
  --stack cert-manager \
  --namespace cert-manager \
  --branch main \
  --context kind-kind \
  --renderer-type kustomize \
  --kustomize-dir . \
  --kustomize-build-args "--enable-helm"
```

**Parameters explained:**
- `--stack` - Unique name for this deployment
- `--namespace` - Target Kubernetes namespace
- `--context` - Kubernetes context (cluster)
- `--renderer-type kustomize` - Use Kustomize renderer
- `--kustomize-dir .` - Relative path to kustomization.yaml (`.` = same as repo root)
- `--kustomize-build-args "--enable-helm"` - **Required for Helm charts**

### 2. Preview Changes (Plan)

```bash
# Simple diff
gitops-lite plan --stack cert-manager

# Detailed line-by-line changes
gitops-lite plan --stack cert-manager --show-diff

# JSON output (for scripting)
gitops-lite plan --stack cert-manager --output json
```

**What happens:**
1. Git repo is pulled (or updated)
2. Kustomize renders with `--enable-helm`
3. CRDs are detected from `charts/` directory
4. `kubectl diff --server-side` shows changes
5. Summary displays added/changed/deleted resources

**First-time CRD deployments:**
```
[WARN] kubectl diff failed: Custom Resource Definitions (CRDs) not yet installed

This is expected for first-time deployment of CRDs.
gitops-lite will automatically order resources during apply:
  1. CustomResourceDefinitions (CRDs)
  2. Namespaces
  3. Custom Resources and other resources

Run 'gitops-lite apply --stack cert-manager --execute' to deploy
```

This is **normal** - `kubectl diff` can't diff CRDs that don't exist yet.

### 3. Apply Changes

```bash
# Dry-run (validates YAML syntax)
gitops-lite apply --stack cert-manager

# Actually apply to cluster
gitops-lite apply --stack cert-manager --execute

# Apply with pruning (removes orphaned resources)
gitops-lite apply --stack cert-manager --execute --prune

# Force resolve field conflicts
gitops-lite apply --stack cert-manager --execute --force-conflicts
```

### 4. Watch for Changes

```bash
# Manual mode (shows diffs, you decide when to apply)
gitops-lite watch --stack cert-manager --interval 60

# Auto-apply mode (automatically applies changes)
gitops-lite watch --stack cert-manager --interval 60 --auto-apply

# Auto-apply with pruning
gitops-lite watch --stack cert-manager --interval 60 --auto-apply --prune
```

---

## Available Examples

### Recommended Examples (Start Here)

#### 1. **cert-manager-example** - Certificate Management
- **Use case:** Automated TLS certificate management
- **Complexity:** Medium
- **CRDs:** Yes (Certificate, ClusterIssuer, etc.)
- **Provider:** Let's Encrypt, self-signed, Vault, etc.

```bash
cd examples/cert-manager-example
cat README.md  # Detailed setup instructions
```

#### 2. **fluentd-example** - Log Collection
- **Use case:** Centralized logging with DaemonSet
- **Complexity:** Low-Medium
- **CRDs:** No
- **Output:** Elasticsearch, S3, stdout

```bash
cd examples/fluentd-example
cat README.md
```

#### 3. **external-dns-example** - DNS Automation
- **Use case:** Automatic DNS records for Services/Ingresses
- **Complexity:** Medium
- **CRDs:** Yes (DNSEndpoint)
- **Providers:** AWS Route53, Cloudflare, Google DNS, Azure DNS

```bash
cd examples/external-dns-example
cat README.md
```

### Other Examples

- **demo-manifests-valide** - Plain YAML (no Helm/Kustomize)
- **kustomize-example-valide** - Kustomize overlays (no Helm)
- **kustomize-crd-example-valide** - Custom CRDs with Kustomize
- **kustomize-helm-example-valide** - Simple Helm chart integration
- **kube-prometheus-stack-example-valide** - Full monitoring stack (advanced)
- **harbor-example-valide** - Container registry
- **metallb-example-valide** - Load balancer for bare-metal
- **istio-example-valide** - Service mesh (advanced)

---

## Command Reference

### Core Commands

#### `link` - Connect Git repo to cluster

```bash
gitops-lite link <repo-path-or-url> \
  --stack <name> \
  --namespace <namespace> \
  --branch <branch> \
  --context <k8s-context> \
  --renderer-type kustomize \
  --kustomize-dir <path> \
  --kustomize-build-args "--enable-helm"
```

**Options:**
- `<repo-path-or-url>` - Local path or Git URL
- `--stack` - **Required** - Unique stack name
- `--namespace` - **Required** - Target namespace
- `--branch` - **Required** - Git branch to track
- `--context` - **Required** - Kubernetes context
- `--renderer-type kustomize` - Enable Kustomize renderer
- `--kustomize-dir` - Path to kustomization.yaml (relative to repo root)
- `--kustomize-build-args` - Args for `kustomize build` (e.g., `"--enable-helm"`)

#### `plan` - Preview changes (dry-run)

```bash
gitops-lite plan --stack <name> [options]
```

**Options:**
- `--stack` - **Required** - Stack name
- `--show-diff` - Show detailed line-by-line changes
- `--output json` - JSON output for scripting
- `--context <ctx>` - Override Kubernetes context
- `--namespace <ns>` - Override namespace

**Exit codes:**
- `0` - No changes
- `1` - Changes detected (normal)
- `>1` - Error occurred

#### `apply` - Deploy to cluster

```bash
gitops-lite apply --stack <name> [--execute] [options]
```

**Options:**
- `--stack` - **Required** - Stack name
- `--execute` - **Required for actual apply** - Without this, runs dry-run
- `--prune` - Remove resources not in manifests (see [Pruning](#pruning))
- `--force-conflicts` - Force resolve field ownership conflicts (see [Force Conflicts](#force-conflicts))
- `--context <ctx>` - Override Kubernetes context
- `--namespace <ns>` - Override namespace

#### `watch` - Continuous synchronization

```bash
gitops-lite watch --stack <name> --interval <seconds> [options]
```

**Options:**
- `--stack` - **Required** - Stack name
- `--interval` - **Required** - Check interval in seconds
- `--auto-apply` - Automatically apply changes (otherwise shows diff only)
- `--prune` - Enable pruning when auto-applying
- `--context <ctx>` - Override Kubernetes context
- `--namespace <ns>` - Override namespace

Press `Ctrl+C` to stop watching.

#### `list` - Show all stacks

```bash
gitops-lite list
```

Shows: Stack name, repository, branch, context, namespace

#### `unlink` - Remove stack

```bash
gitops-lite unlink <stack-name>
```

**What it does:**
1. Removes stack from `~/.gitops-lite/config.yaml`
2. Deletes cached repository from `~/.gitops-lite/repos/<stack>/`
3. **Does NOT delete resources from cluster** - Use `kubectl delete namespace <ns>` for that

---

## Command Details

### Server-Side Apply

All applies use `kubectl apply --server-side` for better conflict resolution.

**Benefits:**
- **Field ownership tracking** - Knows which tool manages which field
- **Better merge logic** - Handles complex updates correctly
- **Large resource support** - No client-side size limits

### Force Conflicts

Use `--force-conflicts` to force field ownership resolution:

```bash
gitops-lite apply --stack my-stack --execute --force-conflicts
```

**When to use:**
- Migrating from client-side apply to server-side apply
- Taking ownership of fields from another tool (Helm, kubectl, etc.)
- Resolving "field managed by other manager" errors

**Example error without `--force-conflicts`:**
```
Apply failed: error when applying patch:
{"metadata":{"annotations":{"meta.helm.sh/release-name":"..."}}}
to "Service/my-service":
Service "my-service" is invalid: metadata.annotations:
Forbidden: field is managed by helm but not in apply configuration
```

**What it does:**
- Adds `--force-conflicts` to `kubectl apply --server-side`
- Forces gitops-lite to become the field manager
- **Use with caution** - Can override changes from other tools

### Pruning

Use `--prune` to remove resources not in manifests:

```bash
gitops-lite apply --stack my-stack --execute --prune
```

**How it works:**
1. Labels all applied resources with `gitops-lite.stack=<stack-name>`
2. Finds all cluster resources with that label
3. Deletes resources not present in current manifests

**Example:**
```
# Before: You had Service A, B, C
# After removing Service C from manifests:
gitops-lite apply --stack my-stack --execute --prune

# Result:
# - Service A: still exists
# - Service B: still exists
# - Service C: DELETED (not in manifests anymore)
```

**Safety:**
- Only affects resources with `gitops-lite.stack=<stack-name>` label
- Never touches resources from other stacks or manually created resources
- Use `--prune` in watch mode for true GitOps (cluster matches Git exactly)

**Warning:**
```bash
# Careful with pruning on namespace changes!
# If you change namespace in kustomization.yaml, old namespace resources
# won't be pruned (different namespace = different label selector)
```

---

## Common Patterns

### Pattern 1: Simple Helm Chart Deployment

**Goal:** Deploy a Helm chart with custom values

**Files:**
```
my-app/base/
├── namespace.yaml
├── kustomization.yaml
└── values.yaml
```

**kustomization.yaml:**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: my-app

resources:
- namespace.yaml

helmCharts:
- name: my-chart
  repo: https://charts.example.com
  version: 1.0.0
  releaseName: my-app
  namespace: my-app
  includeCRDs: false
  valuesFile: values.yaml
```

**Deploy:**
```bash
gitops-lite link ./my-app/base \
  --stack my-app \
  --namespace my-app \
  --branch main \
  --context prod \
  --renderer-type kustomize \
  --kustomize-dir . \
  --kustomize-build-args "--enable-helm"

gitops-lite apply --stack my-app --execute
```

### Pattern 2: Multiple Helm Charts in One Stack

**Goal:** Deploy related charts together (e.g., app + database)

**kustomization.yaml:**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: my-stack

resources:
- namespace.yaml

helmCharts:
- name: postgresql
  repo: https://charts.bitnami.com/bitnami
  version: 12.0.0
  releaseName: db
  namespace: my-stack
  includeCRDs: false
  valuesFile: postgres-values.yaml

- name: my-app
  repo: https://charts.example.com
  version: 1.0.0
  releaseName: app
  namespace: my-stack
  includeCRDs: false
  valuesFile: app-values.yaml
```

**Deploy order:** Gitops-lite automatically orders by resource type (DB first, then app)

### Pattern 3: CRDs + Custom Resources

**Goal:** Deploy CRDs and use them in the same stack

**Structure:**
```
my-operator/base/
├── namespace.yaml
├── kustomization.yaml
├── values.yaml           # Operator Helm chart
└── custom-resources/     # Your custom resources
    ├── kustomization.yaml
    └── my-resource.yaml
```

**base/kustomization.yaml:**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: my-operator

resources:
- namespace.yaml
- custom-resources  # Include custom resources

helmCharts:
- name: my-operator
  repo: https://charts.example.com
  version: 1.0.0
  releaseName: operator
  namespace: my-operator
  includeCRDs: false
  valuesFile: values.yaml
```

**custom-resources/kustomization.yaml:**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- my-resource.yaml
```

**Result:** CRDs from Helm chart applied first, then custom resources

### Pattern 4: Environment-Specific Overlays

**Goal:** Same app, different configs for dev/prod

**Structure:**
```
my-app/
├── base/
│   ├── namespace.yaml
│   ├── kustomization.yaml
│   └── values.yaml
├── overlays/
│   ├── dev/
│   │   ├── kustomization.yaml
│   │   └── values-patch.yaml
│   └── prod/
│       ├── kustomization.yaml
│       └── values-patch.yaml
```

**overlays/dev/kustomization.yaml:**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: my-app-dev

resources:
- ../../base

# Patch values for dev environment
patchesStrategicMerge:
- values-patch.yaml
```

**Deploy dev:**
```bash
gitops-lite link ./my-app/overlays/dev \
  --stack my-app-dev \
  --namespace my-app-dev \
  --branch main \
  --context dev-cluster \
  --renderer-type kustomize \
  --kustomize-dir . \
  --kustomize-build-args "--enable-helm"
```

**Deploy prod:**
```bash
gitops-lite link ./my-app/overlays/prod \
  --stack my-app-prod \
  --namespace my-app-prod \
  --branch main \
  --context prod-cluster \
  --renderer-type kustomize \
  --kustomize-dir . \
  --kustomize-build-args "--enable-helm"
```

---

## Troubleshooting

### CRDs Not Applied

**Problem:**
```
Found 0 CRD(s) in Helm chart(s)
```

**Solutions:**

1. **Check if chart has CRDs:**
   ```bash
   cd examples/my-example/base
   kustomize build --enable-helm . > /tmp/output.yaml
   grep -c "kind: CustomResourceDefinition" /tmp/output.yaml
   ```

2. **Verify charts/ directory:**
   ```bash
   # After kustomize build, check:
   ls -la charts/
   find charts/ -name "*.yaml" | xargs grep -l "CustomResourceDefinition"
   ```

3. **Some charts bundle CRDs differently** - Check chart documentation

### Namespace Issues

**Problem:** Resources created in wrong namespace (e.g., `default` instead of `my-app`)

**Solution:** Add top-level `namespace:` in kustomization.yaml:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: my-app  # Force namespace on ALL resources

resources:
- namespace.yaml

helmCharts:
- name: my-chart
  namespace: my-app  # This is not enough for some charts!
  # ...
```

**Why:** Some Helm charts don't properly set `metadata.namespace` in templates. The top-level `namespace:` forces it.

### Field Conflicts

**Problem:**
```
error: Apply failed: field is managed by helm but not in apply configuration
```

**Solutions:**

1. **Use `--force-conflicts`:**
   ```bash
   gitops-lite apply --stack my-stack --execute --force-conflicts
   ```

2. **Remove Helm release first (if migrating from Helm):**
   ```bash
   helm uninstall my-release -n my-namespace
   gitops-lite apply --stack my-stack --execute
   ```

### Kustomize Build Fails

**Problem:**
```
Error: values don't meet the specifications of the schema
```

**Solutions:**

1. **Check values.yaml syntax:**
   ```bash
   cd examples/my-example/base
   kustomize build --enable-helm .
   # Look for specific error message
   ```

2. **Common issues:**
   - `extraArgs: {}` should be `extraArgs: []` (array not object)
   - Wrong indentation in YAML
   - Missing required fields in values.yaml

3. **Test Helm chart directly:**
   ```bash
   helm template my-release chart-name \
     --repo https://charts.example.com \
     --version 1.0.0 \
     -f values.yaml
   ```

### Watch Mode Not Detecting Changes

**Problem:** Watch doesn't see new commits

**Solutions:**

1. **Check Git remote:**
   ```bash
   cd ~/.gitops-lite/repos/my-stack
   git fetch origin
   git log --oneline -5
   ```

2. **Force re-sync:**
   ```bash
   gitops-lite unlink my-stack
   gitops-lite link ...  # Re-link
   ```

3. **Check branch:**
   ```bash
   # Ensure you're tracking the right branch
   gitops-lite list  # Check branch column
   ```

### Plan Shows "No CRDs" Warning

**Problem:**
```
[WARN] kubectl diff failed: CRDs not yet installed
```

**Solution:** This is **normal for first deployment**. Just apply:

```bash
gitops-lite apply --stack my-stack --execute
```

Gitops-lite will:
1. Apply CRDs first
2. Then apply other resources

---

## Best Practices

### 1. Always Use Version Pinning

```yaml
helmCharts:
- name: cert-manager
  version: v1.19.1  # ✅ Pinned version
  # version: latest  # ❌ Don't use latest
```

### 2. Keep values.yaml Minimal

Only override what you need:

```yaml
# ✅ Good - Only custom values
replicaCount: 3
resources:
  limits:
    memory: 512Mi

# ❌ Bad - Copy-pasting entire default values
# (makes it hard to see what's custom)
```

### 3. Use .gitignore

Always ignore `charts/` directory:

```gitignore
# .gitignore
charts/
```

### 4. Test Locally First

```bash
# Test rendering before linking
cd examples/my-example/base
kustomize build --enable-helm . | kubectl apply --dry-run=client -f -
```

### 5. Use Pruning for True GitOps

```bash
# Cluster exactly matches Git
gitops-lite watch --stack my-stack --interval 60 --auto-apply --prune
```

### 6. Monitor CRD Changes

Watch for CRD updates in Helm chart releases - they may require manual intervention.

---

## Additional Resources

- [Kustomize Documentation](https://kustomize.io/)
- [Kustomize Helm Integration](https://kubectl.docs.kubernetes.io/references/kustomize/builtins/#_helmchartinflationgenerator_)
- [Kubectl Server-Side Apply](https://kubernetes.io/docs/reference/using-api/server-side-apply/)
- [Helm Charts](https://artifacthub.io/)

---

## Getting Help

If you encounter issues:

1. Check example-specific README.md
2. Run with verbose Kustomize output:
   ```bash
   cd examples/my-example/base
   kustomize build --enable-helm .
   ```
3. Check gitops-lite logs during apply
4. Open an issue with:
   - kustomization.yaml
   - Error message
   - Kustomize version (`kustomize version`)
   - Kubectl version (`kubectl version`)
