"""Load manifests, inject labels, sort, serialize."""

from pathlib import Path
from typing import Any

import yaml

from gitops_lite.renderer import RendererConfig, RendererType, render_manifests


def load_manifests(path: Path | str) -> list[dict[str, Any]]:
    """Load YAML manifests from file or directory."""
    path = Path(path)
    documents: list[dict[str, Any]] = []

    if path.is_file():
        documents.extend(_load_yaml_file(path))
    elif path.is_dir():
        # Recursively find all YAML files
        for yaml_file in path.rglob("*.yaml"):
            documents.extend(_load_yaml_file(yaml_file))
        for yml_file in path.rglob("*.yml"):
            documents.extend(_load_yaml_file(yml_file))
    else:
        raise FileNotFoundError(f"Path not found: {path}")

    return documents


def _load_yaml_file(file_path: Path) -> list[dict[str, Any]]:
    """Load YAML file, skip Kustomize files."""
    if file_path.name.lower() in ["kustomization.yaml", "kustomization.yml", "kustomization"]:
        return []

    documents = []
    with open(file_path, "r") as f:
        for doc in yaml.safe_load_all(f):
            if doc and isinstance(doc, dict) and doc.get("kind") != "Kustomization":
                documents.append(doc)

    return documents


def inject_labels(doc: dict[str, Any], stack: str | None = None) -> dict[str, Any]:
    """Inject managed-by and stack labels."""
    if "metadata" not in doc:
        doc["metadata"] = {}
    if "labels" not in doc["metadata"]:
        doc["metadata"]["labels"] = {}

    labels = doc["metadata"]["labels"]
    labels["app.kubernetes.io/managed-by"] = "gitops-lite"
    if stack:
        labels["gitops-lite.stack"] = stack

    return doc


def _get_default_order(kind: str) -> int:
    """Default order by Kind."""
    order_map = {
        "Namespace": 1,
        "CustomResourceDefinition": 2,
        "ConfigMap": 10,
        "Secret": 10,
        "PersistentVolume": 20,
        "PersistentVolumeClaim": 20,
        "StorageClass": 20,
        "ServiceAccount": 30,
        "Role": 31,
        "RoleBinding": 32,
        "ClusterRole": 31,
        "ClusterRoleBinding": 32,
        "Service": 40,
        "Deployment": 50,
        "StatefulSet": 50,
        "DaemonSet": 50,
        "Job": 50,
        "CronJob": 50,
        "Pod": 50,
        "ReplicaSet": 50,
        "Ingress": 60,
        "Route": 60,
        "NetworkPolicy": 70,
        "LimitRange": 70,
        "ResourceQuota": 70,
    }
    return order_map.get(kind, 100)


def _get_document_order(doc: dict[str, Any]) -> int:
    """Get order (annotation override or default)."""
    annotations = doc.get("metadata", {}).get("annotations", {})
    order_annotation = annotations.get("gitops-lite.io/order")
    if order_annotation:
        try:
            return int(order_annotation)
        except (ValueError, TypeError):
            pass
    return _get_default_order(doc.get("kind", ""))


def sort_manifests(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort by application order."""
    return sorted(documents, key=_get_document_order)


def serialize_manifests(documents: list[dict[str, Any]]) -> str:
    """Serialize to YAML stream with --- separators."""
    if not documents:
        return ""
    yaml_parts = [yaml.safe_dump(doc, default_flow_style=False, sort_keys=False) for doc in documents]
    return "---\n".join(yaml_parts)


def split_crds_and_others(documents: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split documents into CRDs and non-CRDs.

    Returns:
        (crds, others) - Two lists of documents
    """
    crds = []
    others = []

    for doc in documents:
        if doc.get("kind") == "CustomResourceDefinition":
            crds.append(doc)
        else:
            others.append(doc)

    return crds, others


def load_manifests_from_yaml_string(yaml_content: str) -> list[dict[str, Any]]:
    """Load from YAML string."""
    documents = []
    for doc in yaml.safe_load_all(yaml_content):
        if doc and isinstance(doc, dict):
            documents.append(doc)
    return documents


def process_manifests(path: Path | str, stack: str | None = None) -> str:
    """Load, sort, inject labels, serialize."""
    documents = load_manifests(path)
    documents = sort_manifests(documents)
    for doc in documents:
        inject_labels(doc, stack=stack)
    return serialize_manifests(documents)


def process_manifests_with_render(
    path: Path | str,
    renderer_config: RendererConfig | None = None,
    stack: str | None = None,
    namespace: str = "default",
    context: str | None = None,
    auto_apply_helm_crds: bool = True,
) -> str:
    """Render (if needed), load, sort, inject labels, serialize.

    Args:
        path: Path to manifests
        renderer_config: Optional renderer configuration
        stack: Stack name for labels
        namespace: Target namespace
        context: Kubernetes context (required for auto Helm CRD application)
        auto_apply_helm_crds: If True, automatically detects and applies CRDs from Helm charts BEFORE rendering

    Returns:
        Serialized YAML manifests
    """
    if renderer_config and renderer_config.renderer_type != RendererType.NONE:
        # Render manifests first (this downloads Helm charts to charts/ directory)
        rendered_yaml = render_manifests(renderer_config, namespace=namespace)

        # Auto-apply Helm CRDs if using Kustomize with --enable-helm
        # Note: We do this AFTER rendering because kustomize build downloads charts
        if (
            auto_apply_helm_crds
            and context
            and renderer_config.renderer_type == RendererType.KUSTOMIZE
            and renderer_config.kustomize_dir
            and renderer_config.kustomize_build_args
            and "--enable-helm" in renderer_config.kustomize_build_args
        ):
            # Import here to avoid circular dependency
            from gitops_lite.helm_crds import handle_helm_crds

            try:
                # Apply Helm CRDs from downloaded charts
                # (charts are now in <kustomize_dir>/charts/ after rendering)
                handle_helm_crds(
                    kustomize_dir=renderer_config.kustomize_dir,
                    context=context,
                    dry_run=False,  # Always apply CRDs, not dry-run
                )
            except Exception as e:
                # Don't fail if CRD application fails - user might handle them manually
                from rich.console import Console
                console = Console()
                console.print(f"[yellow]Warning: Auto-apply Helm CRDs failed: {e}[/yellow]")
                console.print("[yellow]  Continuing with normal rendering...[/yellow]")

        documents = load_manifests_from_yaml_string(rendered_yaml)
    else:
        documents = load_manifests(path)

    documents = sort_manifests(documents)
    for doc in documents:
        inject_labels(doc, stack=stack)
    return serialize_manifests(documents)
