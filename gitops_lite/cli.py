"""CLI interface for gitops-lite using Typer."""

import json
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from types import FrameType

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from gitops_lite import __version__
from gitops_lite.config import StackConfig, load_config, save_config
from gitops_lite.diffparse import count_by_state, filter_metadata_noise, format_diff_items, parse_unified
from gitops_lite.gitlink import GitError, check_for_updates, cleanup_repo, ensure_repo, get_current_commit
from gitops_lite.reconcile import process_manifests, process_manifests_with_render
from gitops_lite.renderer import RendererConfig, RendererType
from gitops_lite.runner import (
    KubectlError,
    check_cluster_available,
    check_namespace_exists,
    kubectl_apply_stdin,
    kubectl_apply_stdin_with_crds,
    kubectl_apply_with_prune,
    kubectl_diff,
    kubectl_diff_stdin,
)

app = typer.Typer(
    name="gitops-lite",
    help="Lightweight GitOps tool for Kubernetes - local-only, CLI-based, no CRDs",
    add_completion=False,
)
console = Console()


def _mask_user_path(path: Path | str) -> str:
    """Mask user-specific paths for privacy in output.

    Args:
        path: File path to mask

    Returns:
        Masked path string (e.g., "~/.cache/gitops-lite/...")
    """
    path_str = str(path)
    home = str(Path.home())

    if path_str.startswith(home):
        return path_str.replace(home, "~", 1)

    return path_str


def _build_renderer_config(stack_config: StackConfig, repo_path: Path) -> RendererConfig | None:
    """Build RendererConfig from StackConfig.

    Args:
        stack_config: Stack configuration with optional renderer settings
        repo_path: Path to the cloned repository

    Returns:
        RendererConfig or None if no renderer configured
    """
    if not stack_config.renderer_type or stack_config.renderer_type == "none":
        return None

    renderer_type = RendererType(stack_config.renderer_type)

    if renderer_type == RendererType.KUSTOMIZE:
        # Resolve kustomize_dir relative to repo_path
        kustomize_dir = repo_path
        if stack_config.renderer_kustomize_dir:
            kustomize_dir = repo_path / stack_config.renderer_kustomize_dir

        return RendererConfig(
            renderer_type=renderer_type,
            kustomize_dir=str(kustomize_dir),
            kustomize_build_args=stack_config.renderer_kustomize_build_args,
        )

    return None


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"gitops-lite version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """gitops-lite: Lightweight GitOps for Kubernetes."""
    pass


@app.command()
def link(
    repo: str = typer.Argument(..., help="Git repository URL or local path"),
    stack: str = typer.Option(..., "--stack", "-s", help="Stack name"),
    namespace: str = typer.Option(..., "--namespace", "-n", help="Target Kubernetes namespace"),
    branch: str = typer.Option(..., "--branch", "-b", help="Git branch (main, master, etc.)"),
    context: str = typer.Option(..., "--context", "-c", help="Kubernetes context"),
    renderer_type: str | None = typer.Option(None, "--renderer-type", help="Renderer: kustomize"),
    kustomize_dir: str | None = typer.Option(None, "--kustomize-dir", help="Kustomize dir (relative to repo)"),
    kustomize_build_args: str | None = typer.Option(None, "--kustomize-build-args", help="Kustomize args (e.g., '--enable-helm')"),
) -> None:
    """Link a repository to a cluster.

    \b
    Example:
      gitops-lite link https://github.com/user/repo \\
          --stack production --namespace prod \\
          --branch main --context prod-cluster
    """
    console.print(f"[cyan]Linking {repo} as stack '{stack}' → namespace '{namespace}'[/cyan]")

    # Check if cluster is available
    if not check_cluster_available(context=context):
        console.print(f"[yellow][WARN][/yellow] Cannot connect to Kubernetes cluster")
        console.print(f"[dim]  Will save configuration, but cluster validation was skipped[/dim]")
    else:
        # Check if namespace exists
        if not check_namespace_exists(namespace=namespace, context=context):
            console.print(f"[red][ERROR][/red] Namespace '{namespace}' does not exist")
            console.print(f"[dim]  Create it first with:[/dim]")
            if context:
                console.print(f"[cyan]  kubectl create namespace {namespace} --context {context}[/cyan]")
            else:
                console.print(f"[cyan]  kubectl create namespace {namespace}[/cyan]")
            raise typer.Exit(1)

    config = load_config()

    build_args_list = None
    if kustomize_build_args:
        build_args_list = kustomize_build_args.split()

    stack_config = StackConfig(
        name=stack,
        repo=repo,
        branch=branch,
        context=context,
        namespace=namespace,
        renderer_type=renderer_type,
        renderer_kustomize_dir=kustomize_dir,
        renderer_kustomize_build_args=build_args_list,
    )

    # Add stack to config
    config.add_stack(stack_config)

    # Save config
    save_config(config)
    console.print(f"[green][OK][/green] Configuration saved")

    # Clone/update repository
    try:
        repo_path = ensure_repo(stack_config)
        commit = get_current_commit(repo_path)
        console.print(f"[green][OK][/green] Repository ready at {_mask_user_path(repo_path)}")
        if commit:
            console.print(f"[dim]  Current commit: {commit}[/dim]")
    except GitError as e:
        console.print(f"[red][ERROR][/red] Failed to clone repository: {e}")
        raise typer.Exit(1)


@app.command()
def list() -> None:
    """List all configured stacks.

    Shows repository, branch, context, namespace for each stack.
    """
    config = load_config()

    if not config.stacks:
        console.print("[yellow]No stacks configured yet. Use 'gitops-lite link' to add one.[/yellow]")
        return

    table = Table(title="Configured Stacks")
    table.add_column("Stack", style="cyan", no_wrap=True)
    table.add_column("Repository", style="white")
    table.add_column("Branch", style="green")
    table.add_column("Context", style="blue")
    table.add_column("Namespace", style="magenta")

    for stack in config.stacks:
        table.add_row(
            stack.name,
            stack.repo,
            stack.branch,
            stack.context or "-",
            stack.namespace or "-",
        )

    console.print(table)


@app.command()
def unlink(
    stack: str = typer.Option(..., "--stack", "-s", help="Stack name to unlink"),
) -> None:
    """Unlink a stack.

    Removes the configuration and cached repository for the specified stack.
    """
    console.print(f"[cyan]Unlinking stack '{stack}'...[/cyan]")

    # Load config
    config = load_config()

    # Get stack to clean up cache
    stack_config = config.get_stack(stack)
    if not stack_config:
        console.print(f"[yellow]Stack '{stack}' not found in configuration[/yellow]")
        raise typer.Exit(1)

    # Remove from config
    removed = config.remove_stack(stack)
    if removed:
        save_config(config)
        console.print(f"[green][OK][/green] Removed '{stack}' from configuration")

    # Cleanup cached repo
    if cleanup_repo(stack_config):
        console.print(f"[green][OK][/green] Removed cached repository")
    else:
        console.print(f"[yellow][WARN][/yellow] No cached repository to remove")


@app.command()
def plan(
    stack: str = typer.Option(..., "--stack", "-s", help="Stack name"),
    context: str | None = typer.Option(None, "--context", "-c", help="Kubernetes context (override stack config)"),
    namespace: str | None = typer.Option(None, "--namespace", "-n", help="Kubernetes namespace (override stack config)"),
    output: str | None = typer.Option(None, "--output", "-o", help="Output format (json)"),
    show_diff: bool = typer.Option(False, "--show-diff", help="Show detailed diffs for each resource"),
) -> None:
    """Show changes that would be applied (using kubectl diff --server-side).

    Requires --stack to be specified. Dry-run only, no changes are made.

    \b
    Example:
      gitops-lite plan --stack production --show-diff
    """
    # Load stack config
    config = load_config()
    stack_config = config.get_stack(stack)
    if not stack_config:
        console.print(f"[red]Stack '{stack}' not found[/red]")
        raise typer.Exit(1)

    # Update/get repo
    try:
        repo_path = ensure_repo(stack_config)
    except GitError as e:
        console.print(f"[red]Failed to access repository: {e}[/red]")
        raise typer.Exit(1)

    # Use stack's context/namespace if not overridden
    ctx = context or stack_config.context
    ns = namespace or stack_config.namespace
    stack_name = stack_config.name

    # Build renderer config if needed
    renderer_config = _build_renderer_config(stack_config, repo_path)

    console.print(f"[cyan]Computing plan for stack '{stack_name}'...[/cyan]")

    # Process manifests with optional rendering, then run kubectl diff
    try:
        if renderer_config:
            # Render manifests first (Kustomize/Helm)
            console.print(f"[cyan]Rendering manifests...[/cyan]")
            yaml_content = process_manifests_with_render(
                path=repo_path,
                renderer_config=renderer_config,
                stack=stack_name,
                namespace=ns or "default",
                context=ctx,
            )
            console.print(f"[green][OK][/green] Manifests rendered")
        else:
            # Process plain manifests (inject labels)
            yaml_content = process_manifests(repo_path, stack=stack_name)

        # Use stdin-based diff with processed manifests (labels injected)
        rc, stdout, stderr = kubectl_diff_stdin(yaml_content, context=ctx, namespace=ns)
    except KubectlError as e:
        console.print(f"[red]kubectl diff failed: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Failed to process manifests: {e}[/red]")
        raise typer.Exit(1)

    # Parse diff output
    if rc == 0:
        console.print("[green][OK] No changes detected[/green]")
        return
    elif rc != 1:
        # Check if error is due to missing CRDs
        if "no matches for kind" in stderr and "ensure CRDs are installed first" in stderr:
            console.print("[yellow][WARN] kubectl diff failed: Custom Resource Definitions (CRDs) not yet installed[/yellow]")
            console.print()
            console.print("[dim]This is expected for first-time deployment of CRDs.[/dim]")
            console.print("[dim]gitops-lite will automatically order resources during apply:[/dim]")
            console.print("[dim]  1. CustomResourceDefinitions (CRDs)[/dim]")
            console.print("[dim]  2. Namespaces[/dim]")
            console.print("[dim]  3. Custom Resources and other resources[/dim]")
            console.print()
            console.print("[cyan]Run 'gitops-lite apply --stack {} --execute' to deploy[/cyan]".format(stack))
            return
        console.print(f"[red]kubectl diff failed: {escape(stderr)}[/red]")
        return

    diff_items = parse_unified(stdout)

    if output == "json":
        # JSON output
        items_dict = [
            {
                "state": item.state,
                "gvk": item.gvk,
                "namespace": item.namespace,
                "name": item.name,
            }
            for item in diff_items
        ]
        print(json.dumps(items_dict, indent=2))
    else:
        # Human-readable Rich output
        counts = count_by_state(diff_items)

        # Summary table
        console.print()
        summary_table = Table(title="Changes Summary", show_header=True, header_style="bold")
        summary_table.add_column("Status", style="cyan", justify="left")
        summary_table.add_column("Count", justify="right")

        summary_table.add_row("[+] ADDED", f"[green]{counts['ADDED']}[/green]")
        summary_table.add_row("[~] CHANGED", f"[yellow]{counts['CHANGED']}[/yellow]")
        summary_table.add_row("[-] DELETED", f"[red]{counts['DELETED']}[/red]")

        console.print(summary_table)
        console.print()

        # Resources table
        if diff_items:
            resources_table = Table(title="Resources", show_header=True, header_style="bold")
            resources_table.add_column("Status", style="cyan", no_wrap=True)
            resources_table.add_column("Resource", style="white")
            resources_table.add_column("Namespace", style="magenta")
            resources_table.add_column("Kind", style="blue")

            for item in diff_items:
                # Status markers
                if item.state == "ADDED":
                    status = "[green][+] ADD[/green]"
                elif item.state == "CHANGED":
                    status = "[yellow][~] CHG[/yellow]"
                else:
                    status = "[red][-] DEL[/red]"

                # Namespace display
                ns_display = item.namespace or "[dim]cluster[/dim]"

                resources_table.add_row(
                    status,
                    item.name,
                    ns_display,
                    item.gvk,
                )

            console.print(resources_table)

            # Show diffs if requested
            if show_diff:
                console.print()
                console.print("[bold cyan]Detailed Diffs:[/bold cyan]")
                console.print()

                for item in diff_items:
                    # Header for each resource
                    if item.state == "ADDED":
                        console.print(f"[bold green][+] {item.gvk}/{item.name}[/bold green] [dim](namespace: {item.namespace or 'cluster'})[/dim]")
                    elif item.state == "CHANGED":
                        console.print(f"[bold yellow][~] {item.gvk}/{item.name}[/bold yellow] [dim](namespace: {item.namespace or 'cluster'})[/dim]")
                    else:
                        console.print(f"[bold red][-] {item.gvk}/{item.name}[/bold red] [dim](namespace: {item.namespace or 'cluster'})[/dim]")

                    # Filter metadata noise before displaying
                    filtered_snippet = filter_metadata_noise(item.snippet)

                    # Display diff snippet with colors
                    if filtered_snippet and filtered_snippet != "(no diff content)":
                        if filtered_snippet == "(only metadata changes)":
                            console.print(f"[dim italic]  {filtered_snippet}[/dim italic]")
                        else:
                            snippet_lines = filtered_snippet.split('\n')

                            # For ADDED/DELETED resources, truncate long diffs to avoid noise
                            max_lines = 15
                            truncated = False
                            if item.state in ("ADDED", "DELETED") and len(snippet_lines) > max_lines:
                                snippet_lines = snippet_lines[:max_lines]
                                truncated = True

                            for line in snippet_lines:
                                if line.startswith('+'):
                                    console.print(f"[bold green]{line}[/bold green]")
                                elif line.startswith('-'):
                                    console.print(f"[bold red]{line}[/bold red]")
                                else:
                                    console.print(f"[dim]{line}[/dim]")

                            if truncated:
                                console.print(f"[dim]  ... ({len(filtered_snippet.split(chr(10))) - max_lines} more lines, use kubectl diff for full output)[/dim]")
                    console.print()


@app.command()
def apply(
    stack: str = typer.Option(..., "--stack", "-s", help="Stack name"),
    context: str | None = typer.Option(None, "--context", "-c", help="Kubernetes context (override stack config)"),
    namespace: str | None = typer.Option(None, "--namespace", "-n", help="Kubernetes namespace (override stack config)"),
    execute: bool = typer.Option(False, "--execute", help="Actually apply changes (default: dry-run)"),
    prune: bool = typer.Option(False, "--prune", help="Prune resources not in manifests"),
    force_conflicts: bool = typer.Option(False, "--force-conflicts", help="Force resolve server-side field conflicts (use with caution)"),
) -> None:
    """Apply manifests to the cluster.

    By default, runs in dry-run mode. Use --execute to actually apply changes.

    \b
    Example:
      gitops-lite apply --stack production --execute
    """
    # Load stack config
    config = load_config()
    stack_config = config.get_stack(stack)
    if not stack_config:
        console.print(f"[red]Stack '{stack}' not found[/red]")
        raise typer.Exit(1)

    # Update/get repo
    try:
        repo_path = ensure_repo(stack_config)
    except GitError as e:
        console.print(f"[red]Failed to access repository: {e}[/red]")
        raise typer.Exit(1)

    # Use stack's context/namespace if not overridden
    ctx = context or stack_config.context
    ns = namespace or stack_config.namespace
    stack_name = stack_config.name

    # Build renderer config if needed
    renderer_config = _build_renderer_config(stack_config, repo_path)

    # Display mode banner
    console.print()
    if execute:
        console.print("[bold green]EXECUTE MODE[/bold green] - Changes will be applied to the cluster")
    else:
        console.print("[bold yellow]DRY-RUN MODE[/bold yellow] - No changes will be made (use --execute to apply)")
    console.print()

    console.print(f"[cyan]Processing manifests for stack '{stack_name}'...[/cyan]")

    # Process manifests (load + optional render + inject labels)
    try:
        if renderer_config:
            yaml_content = process_manifests_with_render(
                path=repo_path,
                renderer_config=renderer_config,
                stack=stack_name,
                namespace=ns or "default",
                context=ctx,
            )
        else:
            yaml_content = process_manifests(repo_path, stack=stack_name)
    except Exception as e:
        console.print(f"[red][ERROR] Failed to process manifests: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"[green][OK][/green] Manifests processed")

    # Apply manifests
    console.print(f"[cyan]Applying to cluster...[/cyan]")
    try:
        if prune and stack_name:
            # Apply with prune (requires stack)
            rc = kubectl_apply_with_prune(
                yaml_content=yaml_content,
                stack_name=stack_name,
                context=ctx,
                namespace=ns,
                dry_run=not execute,
                force_conflicts=force_conflicts,
            )
        else:
            # Apply via stdin with CRD handling (applies CRDs first, then other resources)
            rc = kubectl_apply_stdin_with_crds(
                yaml_content,
                context=ctx,
                namespace=ns,
                dry_run=not execute,
                force_conflicts=force_conflicts,
            )

        if rc != 0:
            console.print(f"[red][ERROR] kubectl apply failed with exit code {rc}[/red]")
            raise typer.Exit(rc)

        # Success summary
        console.print()
        if execute:
            summary_table = Table(show_header=False, box=None, padding=(0, 2))
            summary_table.add_row("[green][OK][/green]", "[bold green]Success![/bold green]", "Manifests applied to the cluster")
            if prune:
                summary_table.add_row("[green][OK][/green]", "[bold]Pruning:[/bold]", "Orphaned resources removed")
            summary_table.add_row("[blue][INFO][/blue]", "[bold]Context:[/bold]", ctx or "default")
            if ns:
                summary_table.add_row("[blue][INFO][/blue]", "[bold]Namespace:[/bold]", ns)
            console.print(summary_table)
        else:
            console.print("[yellow][OK] Dry-run validation passed[/yellow]")
            console.print("[dim]  Use --execute to apply these changes to the cluster[/dim]")

        console.print()

    except KubectlError as e:
        console.print(f"[red][ERROR] kubectl apply failed: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def watch(
    stack: str = typer.Option(..., "--stack", "-s", help="Stack name to watch"),
    interval: int = typer.Option(..., "--interval", "-i", help="Check interval in seconds"),
    auto_apply: bool = typer.Option(False, "--auto-apply", help="Automatically apply changes"),
    prune: bool = typer.Option(False, "--prune", help="Enable pruning when applying"),
    context: str | None = typer.Option(None, "--context", "-c", help="Kubernetes context"),
    namespace: str | None = typer.Option(None, "--namespace", "-n", help="Kubernetes namespace"),
) -> None:
    """Watch a Git repository and automatically sync changes.

    Polls the Git repository at regular intervals and detects new commits.
    When changes are detected, shows the diff and optionally applies them.

    \b
    Example:
      gitops-lite watch --stack production --interval 60 --auto-apply
    """

    # Load stack config
    config = load_config()
    stack_config = config.get_stack(stack)
    if not stack_config:
        console.print(f"[red]Stack '{stack}' not found[/red]")
        raise typer.Exit(1)

    # Use stack's context/namespace if not overridden
    ctx = context or stack_config.context
    ns = namespace or stack_config.namespace

    # Setup signal handler for graceful shutdown
    def signal_handler(sig: int, frame: FrameType | None) -> None:
        console.print("\n[yellow]Shutting down watch mode...[/yellow]")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Initial setup
    console.print(f"[cyan]Starting watch mode for stack '{stack}'[/cyan]")
    console.print(f"[dim]Repository: {stack_config.repo}[/dim]")
    console.print(f"[dim]Branch: {stack_config.branch}[/dim]")
    console.print(f"[dim]Interval: {interval}s[/dim]")
    console.print(f"[dim]Auto-apply: {'enabled' if auto_apply else 'disabled'}[/dim]")
    console.print(f"[dim]Prune: {'enabled' if prune else 'disabled'}[/dim]")
    console.print(f"[dim]Context: {ctx or 'default'}[/dim]")
    console.print(f"[dim]Namespace: {ns or 'all'}[/dim]")
    console.print()

    # Ensure repo exists initially
    try:
        repo_path = ensure_repo(stack_config)
        current_commit = get_current_commit(repo_path)
        console.print(f"[green][OK][/green] Repository initialized at {current_commit}")
    except GitError as e:
        console.print(f"[red]Failed to initialize repository: {e}[/red]")
        raise typer.Exit(1)

    console.print("\n[cyan]Watching for changes... (Press Ctrl+C to stop)[/cyan]\n")

    # Watch loop
    check_count = 0
    while True:
        check_count += 1
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            # Check for updates
            has_updates, old_commit, new_commit = check_for_updates(stack_config)

            if has_updates and old_commit and new_commit:
                console.print(f"[green][OK][/green] [{timestamp}] New commit detected: {old_commit} -> {new_commit}")

                # Update local repo
                try:
                    repo_path = ensure_repo(stack_config)
                except GitError as e:
                    console.print(f"[red]Failed to update repository: {e}[/red]")
                    time.sleep(interval)
                    continue

                # Process manifests and get diff
                try:
                    # Build renderer config if needed
                    renderer_config = _build_renderer_config(stack_config, repo_path)

                    if renderer_config:
                        yaml_content = process_manifests_with_render(
                            path=repo_path,
                            renderer_config=renderer_config,
                            stack=stack_config.name,
                            namespace=ns or "default",
                            context=ctx,
                        )
                    else:
                        yaml_content = process_manifests(repo_path, stack=stack_config.name)
                except Exception as e:
                    console.print(f"[red]Failed to process manifests: {e}[/red]")
                    time.sleep(interval)
                    continue

                # Run kubectl diff
                try:
                    # Use stdin-based diff with processed yaml_content (consistent with apply)
                    rc, stdout, stderr = kubectl_diff_stdin(yaml_content, context=ctx, namespace=ns)

                    if rc == 0:
                        console.print("[dim]  No Kubernetes changes detected[/dim]")
                    elif rc == 1:
                        # Changes detected
                        diff_items = parse_unified(stdout)
                        counts = count_by_state(diff_items)
                        console.print(f"[bold]  Changes detected:[/bold]")
                        console.print(f"    [green]ADDED:[/green]   {counts['ADDED']}")
                        console.print(f"    [yellow]CHANGED:[/yellow] {counts['CHANGED']}")
                        console.print(f"    [red]DELETED:[/red] {counts['DELETED']}")
                        console.print()
                        console.print(format_diff_items(diff_items))
                        console.print()

                        # Auto-apply if enabled
                        if auto_apply:
                            console.print("[cyan]  Auto-applying changes...[/cyan]")
                            try:
                                if prune:
                                    rc = kubectl_apply_with_prune(
                                        yaml_content=yaml_content,
                                        stack_name=stack_config.name,
                                        context=ctx,
                                        namespace=ns,
                                        dry_run=False,
                                    )
                                else:
                                    rc = kubectl_apply_stdin_with_crds(
                                        yaml_content,
                                        context=ctx,
                                        namespace=ns,
                                        dry_run=False,
                                    )

                                if rc == 0:
                                    console.print("[green]  [OK] Changes applied successfully[/green]")
                                else:
                                    console.print(f"[red]  [ERROR] Apply failed with exit code {rc}[/red]")
                            except KubectlError as e:
                                console.print(f"[red]  [ERROR] Apply failed: {e}[/red]")
                        else:
                            console.print("[dim]  (use --auto-apply to apply automatically)[/dim]")
                    else:
                        console.print(f"[red]  kubectl diff failed: {stderr}[/red]")

                except KubectlError as e:
                    console.print(f"[red]Failed to run kubectl diff: {e}[/red]")

                console.print()

            else:
                # No updates
                if check_count % 10 == 0:  # Log every 10 checks
                    console.print(f"[dim][{timestamp}] No changes (check #{check_count})[/dim]")

        except Exception as e:
            console.print(f"[red]Error during watch cycle: {e}[/red]")

        # Wait for next check
        time.sleep(interval)


if __name__ == "__main__":
    app()
