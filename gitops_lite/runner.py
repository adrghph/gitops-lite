"""Kubectl command wrappers for gitops-lite."""

import json
import subprocess
import yaml
from pathlib import Path


class KubectlError(Exception):
    """Exception raised for kubectl operation errors."""

    pass


def kubectl_diff(
    path: Path | str,
    context: str | None = None,
    namespace: str | None = None,
) -> tuple[int, str, str]:
    """Run kubectl diff --server-side on the specified path.

    Returns (returncode, stdout, stderr).
    Note: kubectl diff returns 1 if there are differences, 0 if identical.
    This is expected behavior, not an error.
    """
    cmd = ["kubectl"]

    if context:
        cmd.extend(["--context", context])

    if namespace:
        cmd.extend(["-n", namespace])

    cmd.extend(["diff", "-f", str(path), "--server-side", "--field-manager=gitops-lite"])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        raise KubectlError("kubectl command not found. Please install kubectl.") from None


def kubectl_diff_stdin(
    yaml_content: str,
    context: str | None = None,
    namespace: str | None = None,
) -> tuple[int, str, str]:
    """Run kubectl diff --server-side on YAML content via stdin.

    Returns (returncode, stdout, stderr).
    Note: kubectl diff returns 1 if there are differences, 0 if identical.

    Note: We don't pass -n flag because manifests already contain namespace metadata.
    This allows cluster-scoped resources (Namespace, ClusterRole, etc.) to work correctly.
    """
    cmd = ["kubectl"]

    if context:
        cmd.extend(["--context", context])

    # Don't add -n flag - manifests already specify their namespace
    # This prevents issues with cluster-scoped resources like Namespace

    cmd.extend(["diff", "-f", "-", "--server-side", "--field-manager=gitops-lite"])

    try:
        result = subprocess.run(
            cmd,
            input=yaml_content,
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        raise KubectlError("kubectl command not found. Please install kubectl.") from None


def kubectl_apply_stdin(
    yaml_content: str,
    context: str | None = None,
    namespace: str | None = None,
    dry_run: bool = True,
    force_conflicts: bool = False,
) -> int:
    """Apply YAML content via stdin to kubectl apply --server-side.

    Args:
        yaml_content: YAML manifests to apply
        context: Kubernetes context
        namespace: Target namespace (ignored - manifests specify their own namespace)
        dry_run: If True, runs with --dry-run=server
        force_conflicts: If True, adds --force-conflicts (use with caution!)

    Returns:
        The returncode (0 on success).

    Note: We don't pass -n flag because manifests already contain namespace metadata.
    This allows cluster-scoped resources (Namespace, ClusterRole, etc.) to work correctly.
    """
    cmd = ["kubectl"]

    if context:
        cmd.extend(["--context", context])

    # Don't add -n flag - manifests already specify their namespace
    # This prevents issues with cluster-scoped resources like Namespace

    cmd.extend(["apply", "-f", "-", "--server-side", "--field-manager=gitops-lite"])

    if dry_run:
        cmd.append("--dry-run=server")

    if force_conflicts:
        cmd.append("--force-conflicts")

    try:
        result = subprocess.run(
            cmd,
            input=yaml_content,
            capture_output=True,
            text=True,
        )

        # Print output (kubectl apply is verbose)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="")

        return result.returncode
    except FileNotFoundError:
        raise KubectlError("kubectl command not found. Please install kubectl.") from None


def kubectl_apply_stdin_with_crds(
    yaml_content: str,
    context: str | None = None,
    namespace: str | None = None,
    dry_run: bool = True,
    force_conflicts: bool = False,
) -> int:
    """Apply YAML content with CRD handling - applies CRDs first, then other resources.

    This function parses the YAML content, separates CRDs from other resources,
    and applies them in two passes to avoid validation errors when CRDs are not yet installed.

    In dry-run mode, if Custom Resources fail validation because CRDs are not installed,
    this function will print a warning but return success (0), since this is expected
    behavior for initial deployments.

    Args:
        yaml_content: YAML manifests to apply
        context: Kubernetes context
        namespace: Target namespace (ignored - manifests specify their own namespace)
        dry_run: If True, runs with --dry-run=server
        force_conflicts: If True, adds --force-conflicts (use with caution!)

    Returns:
        The returncode (0 on success).
    """
    from gitops_lite.reconcile import load_manifests_from_yaml_string, serialize_manifests, split_crds_and_others

    # Parse YAML content
    documents = load_manifests_from_yaml_string(yaml_content)

    # Split into CRDs and others
    crds, others = split_crds_and_others(documents)

    # Apply CRDs first (if any)
    if crds:
        print("[cyan]  Applying CRDs first...[/cyan]")
        crd_yaml = serialize_manifests(crds)
        rc = kubectl_apply_stdin(
            yaml_content=crd_yaml,
            context=context,
            namespace=namespace,
            dry_run=dry_run,
            force_conflicts=force_conflicts,
        )
        if rc != 0:
            return rc

    # Apply other resources
    if others:
        if crds:
            print("[cyan]  Applying remaining resources...[/cyan]")
        others_yaml = serialize_manifests(others)

        # In dry-run mode with CRDs, capture stderr to detect CRD validation errors
        if dry_run and crds:
            cmd = ["kubectl"]
            if context:
                cmd.extend(["--context", context])
            cmd.extend(["apply", "-f", "-", "--server-side", "--field-manager=gitops-lite", "--dry-run=server"])
            if force_conflicts:
                cmd.append("--force-conflicts")

            try:
                result = subprocess.run(
                    cmd,
                    input=others_yaml,
                    capture_output=True,
                    text=True,
                )

                # Print stdout
                if result.stdout:
                    print(result.stdout, end="")

                # Check if error is CRD-related
                if result.returncode != 0 and result.stderr:
                    # CRD-related errors can appear in different forms:
                    # - "no matches for kind ... ensure CRDs are installed first"
                    # - "the server could not find the requested resource"
                    is_crd_error = (
                        ("no matches for kind" in result.stderr) or
                        ("the server could not find the requested resource" in result.stderr and "appconfig" in result.stderr.lower())
                    )
                    if is_crd_error:
                        # This is expected in dry-run when CRDs aren't installed yet
                        print("[yellow]  Note: Some Custom Resources could not be validated in dry-run mode[/yellow]")
                        print("[yellow]  This is expected if CRDs are not yet installed. They will be applied in order during --execute[/yellow]")
                        return 0
                    else:
                        # Other error, print it
                        if result.stderr:
                            print(result.stderr, end="")
                        return result.returncode
                elif result.stderr:
                    print(result.stderr, end="")

                return result.returncode
            except FileNotFoundError:
                raise KubectlError("kubectl command not found. Please install kubectl.") from None
        else:
            # Normal apply (no CRDs or not dry-run)
            rc = kubectl_apply_stdin(
                yaml_content=others_yaml,
                context=context,
                namespace=namespace,
                dry_run=dry_run,
                force_conflicts=force_conflicts,
            )
            return rc

    return 0


def kubectl_apply_path(
    path: Path | str,
    context: str | None = None,
    namespace: str | None = None,
    dry_run: bool = True,
) -> int:
    """Apply manifests from a path using kubectl apply --server-side.

    Returns the returncode (0 on success).
    """
    cmd = ["kubectl"]

    if context:
        cmd.extend(["--context", context])

    if namespace:
        cmd.extend(["-n", namespace])

    cmd.extend(["apply", "-f", str(path), "--server-side", "--field-manager=gitops-lite"])

    if dry_run:
        cmd.append("--dry-run=server")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        # Print output
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="")

        return result.returncode
    except FileNotFoundError:
        raise KubectlError("kubectl command not found. Please install kubectl.") from None


def kubectl_apply_with_prune(
    yaml_content: str,
    stack_name: str,
    context: str | None = None,
    namespace: str | None = None,
    dry_run: bool = True,
    force_conflicts: bool = False,
) -> int:
    """Apply manifests with pruning, scoped by gitops-lite.stack label.

    This function:
    1. Applies manifests via stdin (server-side apply)
    2. Lists resources with gitops-lite.stack label
    3. Deletes resources that no longer exist in manifests (pruning)

    NOTE: kubectl apply --prune doesn't work with --server-side, so we implement
    manual pruning by comparing cluster state with manifests.

    Args:
        yaml_content: YAML manifests to apply
        stack_name: Stack name for label scoping
        context: Kubernetes context
        namespace: Target namespace
        dry_run: If True, runs with --dry-run=server
        force_conflicts: If True, adds --force-conflicts (use with caution!)

    Returns:
        The returncode (0 on success).
    """
    # Step 1: Apply manifests with CRD handling
    print("[cyan]Applying manifests...[/cyan]")
    rc = kubectl_apply_stdin_with_crds(
        yaml_content=yaml_content,
        context=context,
        namespace=namespace,
        dry_run=dry_run,
        force_conflicts=force_conflicts,
    )

    if rc != 0:
        return rc

    # Step 2: Prune orphaned resources (only if apply succeeded)
    if not dry_run:  # Only prune on actual apply, not dry-run
        print(f"[cyan]Pruning orphaned resources with label gitops-lite.stack={stack_name}...[/cyan]")
        try:
            prune_rc = _prune_orphaned_resources(
                yaml_content=yaml_content,
                stack_name=stack_name,
                context=context,
                namespace=namespace,
            )
            if prune_rc != 0:
                print(f"[yellow]Warning: Pruning completed with warnings (exit code {prune_rc})[/yellow]")
        except Exception as e:
            print(f"[yellow]Warning: Pruning failed: {e}[/yellow]")
            # Don't fail the whole operation if pruning fails

    return rc


def _prune_orphaned_resources(
    yaml_content: str,
    stack_name: str,
    context: str | None = None,
    namespace: str | None = None,
) -> int:
    """
    Prune resources that have gitops-lite.stack label but are no longer in manifests.

    Returns:
        0 on success, non-zero if any deletions failed
    """
    # Parse manifests to get list of resources
    manifest_resources = _extract_resources_from_yaml(yaml_content)
    manifest_keys = {
        (r["apiVersion"], r["kind"], r.get("metadata", {}).get("namespace", namespace or ""), r["metadata"]["name"])
        for r in manifest_resources
    }

    # Get all resources with the stack label from cluster
    cluster_resources = _list_resources_with_label(
        stack_name=stack_name,
        context=context,
        namespace=namespace,
    )

    # Find orphaned resources (in cluster but not in manifests)
    orphaned = []
    for res in cluster_resources:
        res_key = (res["apiVersion"], res["kind"], res["namespace"], res["name"])
        if res_key not in manifest_keys:
            orphaned.append(res)

    if not orphaned:
        print("[dim]  No orphaned resources to prune[/dim]")
        return 0

    # Delete orphaned resources
    print(f"[yellow]  Found {len(orphaned)} orphaned resource(s) to delete[/yellow]")
    failed = 0
    for res in orphaned:
        print(f"[dim]  Deleting {res['kind']}/{res['name']} (namespace: {res['namespace'] or 'cluster-scoped'})[/dim]")
        rc = _delete_resource(
            kind=res["kind"],
            name=res["name"],
            namespace=res["namespace"],
            context=context,
        )
        if rc != 0:
            failed += 1

    if failed > 0:
        print(f"[yellow]  Warning: {failed} resource(s) failed to delete[/yellow]")
        return 1

    print(f"[green]  Successfully pruned {len(orphaned)} orphaned resource(s)[/green]")
    return 0


def _extract_resources_from_yaml(yaml_content: str) -> list[dict]:
    """Extract list of resources from YAML manifests."""
    resources = []
    for doc in yaml.safe_load_all(yaml_content):
        if doc and isinstance(doc, dict) and "kind" in doc and "metadata" in doc:
            resources.append(doc)
    return resources


def _list_resources_with_label(
    stack_name: str,
    context: str | None = None,
    namespace: str | None = None,
) -> list[dict]:
    """
    List all resources with gitops-lite.stack label.

    Returns list of dicts with keys: apiVersion, kind, namespace, name
    """
    cmd = ["kubectl", "get", "all,configmap,secret,ingress,pvc,serviceaccount"]

    if context:
        cmd.extend(["--context", context])

    if namespace:
        cmd.extend(["-n", namespace])
    else:
        cmd.append("--all-namespaces")

    cmd.extend([
        "-l", f"gitops-lite.stack={stack_name}",
        "-o", "json",
    ])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            # No resources found is OK
            return []

        data = json.loads(result.stdout)
        resources = []

        for item in data.get("items", []):
            resources.append({
                "apiVersion": item.get("apiVersion", ""),
                "kind": item.get("kind", ""),
                "namespace": item.get("metadata", {}).get("namespace", ""),
                "name": item.get("metadata", {}).get("name", ""),
            })

        return resources

    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return []


def _delete_resource(
    kind: str,
    name: str,
    namespace: str | None,
    context: str | None = None,
) -> int:
    """Delete a single resource."""
    cmd = ["kubectl", "delete", kind, name]

    if context:
        cmd.extend(["--context", context])

    if namespace:
        cmd.extend(["-n", namespace])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 1


def check_kubectl_available() -> bool:
    """Check if kubectl is available in PATH."""
    try:
        result = subprocess.run(
            ["kubectl", "version", "--client", "--output=yaml"],
            capture_output=True,
            check=True,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def check_cluster_available(context: str | None = None) -> bool:
    """Check if the Kubernetes cluster is accessible."""
    cmd = ["kubectl", "cluster-info"]
    if context:
        cmd.extend(["--context", context])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def check_namespace_exists(namespace: str, context: str | None = None) -> bool:
    """Check if a namespace exists in the cluster.

    Args:
        namespace: The namespace name to check
        context: Kubernetes context (optional)

    Returns:
        True if namespace exists, False otherwise
    """
    cmd = ["kubectl", "get", "namespace", namespace]
    if context:
        cmd.extend(["--context", context])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
