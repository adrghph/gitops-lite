"""
Helm CRDs auto-detection and auto-application.

When using Kustomize with helmCharts and --enable-helm, Kustomize downloads
Helm charts to a local cache (<kustomize_dir>/charts/) during the build process.
This module detects CRDs in those downloaded charts and automatically applies
them to the cluster, avoiding the common "includeCRDs: true" parsing error with
large charts like kube-prometheus-stack.

The flow is:
1. kustomize build --enable-helm runs (downloads charts to charts/ directory)
2. This module scans charts/*/crds/ for CRD YAML files
3. Applies CRDs using kubectl apply --server-side
4. Main manifests are then processed normally
"""

import subprocess
from pathlib import Path

from rich.console import Console

console = Console()


def find_helm_chart_crds(kustomize_dir: Path) -> list[Path]:
    """
    Find CRDs in Helm charts downloaded by Kustomize using recursive search.

    This function recursively scans ALL YAML files in the charts/ directory
    and validates them by checking for `kind: CustomResourceDefinition`.

    This approach is robust and works with ANY chart structure:
    - charts/*/crds/*.yaml (kube-prometheus-stack)
    - charts/*/crds/templates/*.yaml (MetalLB)
    - charts/*/templates/crds/*.yaml (some charts)
    - charts/*/templates/*-crd.yaml (other charts)
    - Any other structure

    Args:
        kustomize_dir: Path to the directory containing kustomization.yaml

    Returns:
        List of paths to CRD YAML files (validated by content)
    """
    import yaml

    crd_files = []

    # Check for charts directory
    charts_dir = kustomize_dir / "charts"
    if not charts_dir.exists():
        return crd_files

    # Recursively find ALL YAML files in charts/
    all_yaml_files = list(charts_dir.rglob("*.yaml")) + list(charts_dir.rglob("*.yml"))

    for yaml_file in all_yaml_files:
        # Skip Helm metadata files (not Kubernetes resources)
        if yaml_file.name.lower() in ["chart.yaml", "chart.yml", "values.yaml", "values.yml"]:
            continue

        # Skip test files and example files (common in charts)
        if "/tests/" in str(yaml_file) or "/examples/" in str(yaml_file):
            continue

        # Skip files in templates/ directories - these are Helm templates
        # that will be rendered by kustomize build --enable-helm
        if "/templates/" in str(yaml_file):
            continue

        # Check if file contains Helm templates (not yet rendered)
        # If it does, skip it - these will be rendered and applied by Kustomize
        try:
            with open(yaml_file, "r") as f:
                content = f.read()

            # Skip files with Helm template syntax ({{ }})
            # These files need to be rendered by Helm first
            if "{{" in content and "}}" in content:
                continue

            # Validate it's a CRD by parsing the content
            for doc in yaml.safe_load_all(content):
                if doc and isinstance(doc, dict):
                    # Check if it's a CustomResourceDefinition
                    if doc.get("kind") == "CustomResourceDefinition":
                        crd_files.append(yaml_file)
                        break  # Only need to find one CRD in the file
        except (yaml.YAMLError, UnicodeDecodeError, IOError):
            # Skip files that can't be parsed (invalid YAML, binary files, etc.)
            continue

    return sorted(crd_files)


def apply_crds_first(
    crd_files: list[Path],
    context: str,
    dry_run: bool = False
) -> bool:
    """
    Apply CRDs to the cluster before the main resources.

    Uses kubectl apply --server-side to handle large CRDs properly.

    Args:
        crd_files: List of CRD file paths to apply
        context: Kubernetes context to use
        dry_run: If True, only shows what would be applied

    Returns:
        True if CRDs were applied successfully, False otherwise

    Raises:
        RuntimeError: If kubectl command fails
    """
    if not crd_files:
        return False

    console.print(
        f"[yellow]Found {len(crd_files)} CRD(s) in Helm chart(s)[/yellow]"
    )

    if dry_run:
        console.print("[dim]  Would apply CRDs first (server-side apply)[/dim]")
        for crd in crd_files:
            console.print(f"[dim]    - {crd.name}[/dim]")
        return True

    console.print("[dim]  Applying CRDs first (server-side apply)...[/dim]")

    for crd_file in crd_files:
        try:
            # Use server-side apply for CRDs (better for large resources)
            cmd = [
                "kubectl",
                "apply",
                "--server-side",
                "--force-conflicts",
                "-f", str(crd_file),
                "--context", context,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )

            console.print(f"[dim]    ✓ {crd_file.name}[/dim]")

        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to apply CRD {crd_file.name}:\n{e.stderr}"
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Timeout applying CRD {crd_file.name} (30s)"
            )

    console.print("[green]  ✓ All CRDs applied successfully[/green]")
    return True


def handle_helm_crds(
    kustomize_dir: str,
    context: str,
    dry_run: bool = False
) -> bool:
    """
    Main entry point: Detect and apply Helm chart CRDs after kustomize downloads them.

    This function:
    1. Searches for CRDs in Helm charts downloaded by Kustomize (in charts/ subdirectory)
    2. Applies them to the cluster using server-side apply
    3. Returns True if CRDs were found and applied

    Usage:
        After calling kustomize build --enable-helm (which populates charts/ dir):
        >>> handle_helm_crds("/path/to/kustomize/dir", "my-cluster", dry_run=False)

    Args:
        kustomize_dir: Path to directory containing kustomization.yaml
        context: Kubernetes context to use
        dry_run: If True, only shows what would be applied

    Returns:
        True if CRDs were found and applied, False if no CRDs found

    Raises:
        RuntimeError: If CRD application fails
    """
    kustomize_path = Path(kustomize_dir).resolve()

    # Find CRDs in Helm charts
    crd_files = find_helm_chart_crds(kustomize_path)

    if not crd_files:
        # No CRDs found, nothing to do
        return False

    # Apply CRDs before rendering the rest
    return apply_crds_first(crd_files, context, dry_run=dry_run)
